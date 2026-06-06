"""
图神经网络模块 — 对视频之间的关系进行图建模

核心功能：
    1. 构建视频关联图
       - 边权重基于：同UP主、发布时间接近度、互动率相似度
    2. 图嵌入（双引擎）
       - PyTorch 可用时：两层 GCN + 自监督图重构训练
       - PyTorch 不可用时（fallback）：拉普拉斯特征映射（numpy 实现）
    3. 输出图增强特征 → 注入到预测算法的特征向量中
"""

import math
import threading
import logging
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict
import numpy as np

logger = logging.getLogger(__name__)

# ── PyTorch 检测（可选依赖） ─────────────────────
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False


if _HAS_TORCH:

    class _GCN(nn.Module):
        """两层图卷积网络。"""

        def __init__(self, in_dim: int, hidden_dim: int, out_dim: int):
            super().__init__()
            self.gcn1 = nn.Linear(in_dim, hidden_dim)
            self.gcn2 = nn.Linear(hidden_dim, out_dim)

        def forward(self, x, adj):
            h = torch.relu(adj @ self.gcn1(x))
            return adj @ self.gcn2(h)


class VideoGraph:
    """视频关联图 + 简化图神经网络。

    节点：每个被监控的视频（用 BV 号标识）
    边：基于同UP主 / 发布时间差 / 互动率相似度计算的加权边
    特征：每个视频提取 12 维统计特征向量

    用法
    ----
    >>> graph = VideoGraph()
    >>> graph.update_node('BV1xxx', video_info)
    >>> graph.update_node('BV2yyy', video_info)
    >>> graph.build_edges()
    >>> graph.train()
    >>> feat = graph.get_node_features('BV1xxx')
    """

    # 每个节点的原始特征维度
    FEATURE_DIM = 12

    def __init__(self, edge_threshold: float = 0.3, k_neighbors: int = 5):
        """初始化视频图。

        Args:
            edge_threshold: 边权重阈值，低于此值不建边
            k_neighbors:    每个节点最多保留的邻居数（k-NN 截断）
        """
        self._edge_threshold = edge_threshold
        self._k_neighbors = k_neighbors
        self._lock = threading.RLock()

        # 节点数据
        self._nodes: Dict[str, Dict] = {}  # bvid → video_info
        self._features: Dict[str, List[float]] = {}  # bvid → 特征向量
        self._adj: Dict[str, Dict[str, float]] = defaultdict(dict)  # 邻接表 {bvid: {nbvid: weight}}
        self._bvid_list: List[str] = []  # 有序节点列表

        # 脏标记：节点有变更时置 True，build_edges 后清 False
        self._edges_dirty = True

        # 缓存的嵌入向量（train 后填充）
        self._embeddings: Optional[Dict[str, List[float]]] = None

    def update_node(self, bvid: str, video_info: Dict):
        """更新或添加一个视频节点，自动提取特征并置脏边标记。

        Parameters
        ----------
        bvid : str
            视频 BV 号
        video_info : dict
            需包含 view_count, like_count, coin_count, share_count,
            favorite_count, danmaku_count, reply_count, owner_name, pubdate, duration 等字段
        """
        with self._lock:
            self._nodes[bvid] = dict(video_info)
            self._features[bvid] = self._extract_features(video_info)
            if bvid not in self._bvid_list:
                self._bvid_list.append(bvid)
            self._edges_dirty = True  # 节点变更，边需重建
            self._embeddings = None  # 使缓存失效

    def remove_node(self, bvid: str):
        """从图中移除指定节点及其所有关联边。"""
        with self._lock:
            self._nodes.pop(bvid, None)
            self._features.pop(bvid, None)
            self._adj.pop(bvid, None)
            for nb in self._adj:
                self._adj[nb].pop(bvid, None)
            if bvid in self._bvid_list:
                self._bvid_list.remove(bvid)
            self._edges_dirty = True
            self._embeddings = None

    def build_edges(self):
        """根据当前所有节点数据构建图边。

        内部流程：
            1. 若 _edges_dirty 为 False 则直接跳过（缓存加速）
            2. 两两计算边权重，仅保留 >= threshold 的边
            3. k-NN 截断：每个节点至多保留 k 个最强邻居
            4. 清除 _embeddings 缓存
        """
        with self._lock:
            if not self._edges_dirty:
                return
            self._adj.clear()
            bvids = list(self._nodes.keys())
            n = len(bvids)
            if n < 5:  # 节点太少时建边无意义，保留脏标记等积累更多节点
                return

            # 两两计算相似度
            for i in range(n):
                for j in range(i + 1, n):
                    bi, bj = bvids[i], bvids[j]
                    w = self._compute_edge_weight(self._nodes[bi], self._nodes[bj])
                    if w >= self._edge_threshold:
                        self._adj[bi][bj] = w
                        self._adj[bj][bi] = w

            # k-NN 截断：每个节点只保留 k 个权重最高的邻居
            for bi in bvids:
                neighbors = sorted(self._adj[bi].items(), key=lambda x: -x[1])
                if len(neighbors) > self._k_neighbors:
                    self._adj[bi] = dict(neighbors[: self._k_neighbors])
                    # 同步清理被截断邻居的反向引用
                    kept = set(self._adj[bi].keys())
                    for bj in bvids:
                        if bj != bi and bj not in kept:
                            self._adj[bj].pop(bi, None)

            self._embeddings = None
            self._edges_dirty = False

    def _compute_embedding_numpy(self, embed_dim: int = 4) -> Dict[str, List[float]]:
        """拉普拉斯特征映射（numpy fallback）。

        当 PyTorch 不可用时，使用对称归一化拉普拉斯矩阵的
        最小非零特征向量作为确定性图嵌入。
        """
        bvids = self._bvid_list
        n = len(bvids)
        if n < 2:
            return {bv: [0.0] * embed_dim for bv in bvids}

        idx = {bv: i for i, bv in enumerate(bvids)}
        A = np.zeros((n, n))
        for bi in bvids:
            i = idx[bi]
            for bj, w in self._adj.get(bi, {}).items():
                if bj in idx:
                    j = idx[bj]
                    A[i, j] = w

        deg = np.maximum(A.sum(axis=1), 1e-10)
        D_inv_sqrt = np.diag(1.0 / np.sqrt(deg))
        L = np.eye(n) - D_inv_sqrt @ A @ D_inv_sqrt

        # 特征分解，取第 2 到 embed_dim+1 小的特征向量
        _, eigenvectors = np.linalg.eigh(L)
        actual_dim = min(embed_dim, max(1, n - 1))
        embs = eigenvectors[:, 1 : actual_dim + 1]
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        norms = np.where(norms > 1e-10, norms, 1.0)
        embs = embs / norms

        return {bv: embs[i, :].tolist() for i, bv in enumerate(bvids)}

    def _compute_embedding_torch(
        self, embed_dim: int = 4, hidden_dim: int = 16, epochs: int = 100, lr: float = 0.01
    ) -> Dict[str, List[float]]:
        """PyTorch GCN：两层图卷积网络 + 自监督图重构训练。

        训练目标：最小化重构邻接矩阵与原始邻接矩阵的 MSE 损失。
        """
        bvids = self._bvid_list
        n = len(bvids)
        if n < 2:
            return {bv: [0.0] * embed_dim for bv in bvids}

        # 构建特征矩阵和邻接矩阵
        idx = {bv: i for i, bv in enumerate(bvids)}
        X = np.array([self._features.get(bv, [0.0] * self.FEATURE_DIM) for bv in bvids], dtype=np.float32)
        A = np.zeros((n, n), dtype=np.float32)
        for bi in bvids:
            i = idx[bi]
            for bj, w in self._adj.get(bi, {}).items():
                if bj in idx:
                    j = idx[bj]
                    A[i, j] = w

        deg = np.maximum(A.sum(axis=1), 1e-10)
        D_inv_sqrt = np.diag(1.0 / np.sqrt(deg))
        A_norm = D_inv_sqrt @ A @ D_inv_sqrt

        X_t = torch.tensor(X)
        A_t = torch.tensor(A_norm)

        model = _GCN(self.FEATURE_DIM, hidden_dim, embed_dim)
        optimizer = optim.Adam(model.parameters(), lr=lr)

        # 自监督训练：重构邻接矩阵
        for _ in range(epochs):
            model.train()
            optimizer.zero_grad()
            emb = model(X_t, A_t)
            recon = torch.sigmoid(emb @ emb.T)
            loss = nn.functional.mse_loss(recon, A_t)
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            emb = model(X_t, A_t).numpy()

        return {bv: emb[i, :].tolist() for i, bv in enumerate(bvids)}

    def get_node_features(self, bvid: str, embeddings: Optional[Dict[str, List[float]]] = None) -> List[float]:
        """获取某视频的图增强特征向量。

        拼接三部分：
            - 自身原始特征（12 维）
            - 邻居聚合特征（加权平均，12 维）
            - GCN 图嵌入（4 维）
        总维度：28

        Returns:
            list[float]: 拼接后的特征向量
        """
        with self._lock:
            own = self._features.get(bvid, [0.0] * self.FEATURE_DIM)

            # 邻居聚合特征（加权平均）
            neighbors = self._adj.get(bvid, {})
            if neighbors:
                total_w = 0.0
                for _, w in neighbors.items():
                    total_w += w
                agg = [0.0] * self.FEATURE_DIM
                if total_w > 0:
                    for nb, w in neighbors.items():
                        f = self._features.get(nb, [0.0] * self.FEATURE_DIM)
                        for j in range(self.FEATURE_DIM):
                            agg[j] += f[j] * w / total_w
            else:
                agg = [0.0] * self.FEATURE_DIM

            # GCN 嵌入
            emb = [0.0] * 4
            if embeddings:
                emb = embeddings.get(bvid, [0.0] * 4)

            # 拼接：自身(12) + 邻居聚合(12) + 嵌入(4) = 28 维
            return own + agg + emb

    def train(self, embed_dim: int = 4) -> None:
        """训练图嵌入。

        PyTorch 可用 → GCN 训练（_compute_embedding_torch）
        PyTorch 不可用 → 拉普拉斯特征映射 fallback（_compute_embedding_numpy）

        若图数据未变更（_edges_dirty = False 且缓存存在）则跳过训练。
        """
        with self._lock:
            self._bvid_list = list(self._nodes.keys())
            if not self._edges_dirty and self._embeddings is not None:
                return
            if self._edges_dirty:
                self.build_edges()
            if _HAS_TORCH:
                self._embeddings = self._compute_embedding_torch(embed_dim)
            else:
                self._embeddings = self._compute_embedding_numpy(embed_dim)

    def get_graph_stats(self) -> Dict:
        """获取图结构的统计信息（节点数、边数、平均/最大度数等）。"""
        with self._lock:
            total_edges = sum(len(nb) for nb in self._adj.values()) // 2
            degrees = [len(self._adj.get(bv, {})) for bv in self._bvid_list]
            avg_degree = sum(degrees) / len(degrees) if degrees else 0
            max_degree = max(degrees) if degrees else 0
            return {
                "num_nodes": len(self._bvid_list),
                "num_edges": total_edges,
                "avg_degree": round(avg_degree, 2),
                "max_degree": max_degree,
                "feature_dim": self.FEATURE_DIM,
            }

    # ── 内部方法 ──────────────────────────────────

    def _extract_features(self, info: Dict) -> List[float]:
        """从视频信息中提取 12 维特征向量。

        特征构成：
            1. 播放量对数
            2. 点赞率
            3. 投币率
            4. 分享率
            5. 收藏率
            6. 弹幕率
            7. 评论率
            8. 在线率
            9. 时长对数
            10. 综合互动率
            11. 投币/点赞比
            12. 弹幕/评论比
        """
        views = max(info.get("view_count", 0), 1)
        likes = info.get("like_count", 0) or 0
        coins = info.get("coin_count", 0) or 0
        shares = info.get("share_count", 0) or 0
        favs = info.get("favorite_count", 0) or 0
        danmaku = info.get("danmaku_count", 0) or 0
        replies = info.get("reply_count", 0) or 0
        viewers = info.get("viewers_total", 0) or 0
        duration = max(info.get("duration", 0), 1)

        return [
            math.log10(max(views, 1)),  # 1. 播放量对数
            likes / views,  # 2. 点赞率
            coins / views,  # 3. 投币率
            shares / views,  # 4. 分享率
            favs / views,  # 5. 收藏率
            danmaku / views,  # 6. 弹幕率
            replies / views,  # 7. 评论率
            viewers / max(views, 1),  # 8. 在线率
            math.log10(max(duration, 1)),  # 9. 时长对数
            (likes + coins + favs + shares) / views,  # 10. 综合互动率
            coins / max(likes, 1),  # 11. 投币/点赞比
            danmaku / max(replies, 1),  # 12. 弹幕/评论比
        ]

    def _compute_edge_weight(self, a: Dict, b: Dict) -> float:
        """计算两个视频之间的边权重，范围 [0, 1]。

        三个子维度：
            1. 同UP主（强关联，最高 0.5）
            2. 发布时间接近度（48 小时内，最高 0.3）
            3. 互动率相似度（最高 0.2）
        """
        w = 0.0
        count = 0

        # 1. 同UP主（强关联）
        if a.get("owner_name") and b.get("owner_name"):
            if a["owner_name"] == b["owner_name"]:
                w += 0.5
                count += 1

        # 2. 发布时间接近度（48 小时以内视为相关，越接近权重越高）
        pa = a.get("pubdate", "")
        pb = b.get("pubdate", "")
        if pa and pb:
            try:
                ta = datetime.fromisoformat(str(pa)).timestamp() if isinstance(pa, str) else float(pa)
                tb = datetime.fromisoformat(str(pb)).timestamp() if isinstance(pb, str) else float(pb)
                dt_hours = abs(ta - tb) / 3600.0
                if dt_hours < 48:
                    w += 0.3 * (1 - dt_hours / 48)
                    count += 1
            except Exception as e:
                logger.debug("计算视频间发布时间特征失败: %s", e)

        # 3. 互动率相似度（点赞率差异越小 → 越相似）
        va = max(a.get("view_count", 0), 1)
        vb = max(b.get("view_count", 0), 1)
        eng_a = (a.get("like_count", 0) or 0) / va
        eng_b = (b.get("like_count", 0) or 0) / vb
        eng_diff = abs(eng_a - eng_b)
        w += 0.2 * max(0, 1 - eng_diff * 100)
        count += 1

        if count == 0:
            return 0.0
        return min(1.0, w)


# ── 全局单例 ────────────────────────────────────────
_global_graph: Optional[VideoGraph] = None
_graph_lock = threading.Lock()


def get_video_graph() -> VideoGraph:
    """获取全局 VideoGraph 单例（双检锁惰性初始化）。"""
    global _global_graph
    with _graph_lock:
        if _global_graph is None:
            _global_graph = VideoGraph()
        return _global_graph
