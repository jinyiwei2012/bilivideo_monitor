"""
图神经网络模块 — 考虑视频之间的关系

在纯 Python 环境下（无 PyTorch Geometric），使用邻接矩阵 + 简化 GCN 实现：

1. 构建视频关联图
   - 边权重基于：(a) 同UP主, (b) 增长率相似度, (c) 发布时间接近度, (d) 互动率相似度
2. 两层简化 GCN
   - H^(1) = σ(Ã·H^(0)·W^(0))
   - H^(2) = Ã·H^(1)·W^(1)
3. 输出图嵌入 → 注入到预测算法的特征中

不依赖 torch / DGL，纯 numpy 实现。
"""

import math
import threading
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime
from collections import defaultdict


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-15 else 0.0


def _softmax(x: List[float]) -> List[float]:
    if not x:
        return []
    m = max(x)
    exps = [math.exp(xi - m) for xi in x]
    s = sum(exps)
    return [e / s for s, e in zip([s] * len(exps), exps)]


def _relu(x: float) -> float:
    return max(0.0, x)


def _mat_vec_mul(mat: List[List[float]], vec: List[float]) -> List[float]:
    """矩阵 × 向量"""
    n = len(mat)
    result = []
    for i in range(n):
        s = sum(mat[i][j] * vec[j] for j in range(len(vec)))
        result.append(s)
    return result


def _vec_outer(a: List[float], b: List[float]) -> List[List[float]]:
    """向量外积 a × b^T"""
    return [[ai * bj for bj in b] for ai in a]


def _mat_add_bias(mat: List[List[float]], bias: List[float]) -> List[List[float]]:
    """矩阵每列加偏置"""
    return [[mat[i][j] + bias[j] for j in range(len(bias))] for i in range(len(mat))]


def _element_wise_relu(mat: List[List[float]]) -> List[List[float]]:
    return [[_relu(x) for x in row] for row in mat]


class VideoGraph:
    """视频关联图 + 简化 GCN。

    节点：每个被监控的视频
    边：基于多种相似度指标构建
    特征：每个视频的统计特征向量

    Usage
    -----
    >>> graph = VideoGraph()
    >>> graph.update_node('BV1xxx', video_info)
    >>> graph.update_node('BV2yyy', video_info)
    >>> graph.build_edges()
    >>> embeddings = graph.compute_gcn()
    >>> feat = graph.get_node_features('BV1xxx', embeddings)
    """

    # 特征维度
    FEATURE_DIM = 12

    def __init__(self, edge_threshold: float = 0.3, k_neighbors: int = 5):
        self._edge_threshold = edge_threshold
        self._k_neighbors = k_neighbors
        self._lock = threading.Lock()

        # 节点数据
        self._nodes: Dict[str, Dict] = {}           # bvid -> video_info
        self._features: Dict[str, List[float]] = {}  # bvid -> feature_vec
        self._adj: Dict[str, Dict[str, float]] = defaultdict(dict)  # bvid -> {nbvid: weight}
        self._bvid_list: List[str] = []               # 有序节点列表

        # GCN 权重（小型随机初始化）
        self._W0: Optional[List[List[float]]] = None
        self._W1: Optional[List[List[float]]] = None
        self._b0: Optional[List[float]] = None
        self._b1: Optional[List[float]] = None

        # 缓存的嵌入
        self._embeddings: Optional[Dict[str, List[float]]] = None

    def update_node(self, bvid: str, video_info: Dict):
        """更新或添加一个视频节点。

        Parameters
        ----------
        bvid : str
        video_info : dict
            需要包含 view_count, like_count, coin_count, share_count,
            favorite_count, danmaku_count, reply_count, owner_name, pubdate, duration 等。
        """
        with self._lock:
            self._nodes[bvid] = dict(video_info)
            self._features[bvid] = self._extract_features(video_info)
            if bvid not in self._bvid_list:
                self._bvid_list.append(bvid)
            self._embeddings = None  # 失效缓存

    def remove_node(self, bvid: str):
        """移除节点。"""
        with self._lock:
            self._nodes.pop(bvid, None)
            self._features.pop(bvid, None)
            self._adj.pop(bvid, None)
            for nb in self._adj:
                self._adj[nb].pop(bvid, None)
            if bvid in self._bvid_list:
                self._bvid_list.remove(bvid)
            self._embeddings = None

    def build_edges(self):
        """根据当前节点数据重新构建边。"""
        with self._lock:
            self._adj.clear()
            bvids = list(self._nodes.keys())
            n = len(bvids)
            if n < 2:
                return

            for i in range(n):
                for j in range(i + 1, n):
                    bi, bj = bvids[i], bvids[j]
                    w = self._compute_edge_weight(self._nodes[bi], self._nodes[bj])
                    if w >= self._edge_threshold:
                        self._adj[bi][bj] = w
                        self._adj[bj][bi] = w

            # k-NN 截断：每个节点最多保留 k 个最强邻居
            for bi in bvids:
                neighbors = sorted(self._adj[bi].items(), key=lambda x: -x[1])
                if len(neighbors) > self._k_neighbors:
                    self._adj[bi] = dict(neighbors[:self._k_neighbors])
                    # 同时清理反向
                    kept = set(self._adj[bi].keys())
                    for bj in bvids:
                        if bj != bi and bj not in kept:
                            self._adj[bj].pop(bi, None)

            self._embeddings = None

    def compute_gcn(self, hidden_dim: int = 8, embed_dim: int = 4) -> Dict[str, List[float]]:
        """运行两层简化 GCN，返回每个节点的嵌入向量。

        Returns
        -------
        dict : {bvid: [e1, e2, e3, e4], ...}
        """
        with self._lock:
            bvids = self._bvid_list
            n = len(bvids)
            if n < 2:
                return {bv: [0.0] * embed_dim for bv in bvids}

            # 构建特征矩阵 X: n × FEATURE_DIM
            X = [self._features.get(bv, [0.0] * self.FEATURE_DIM) for bv in bvids]

            # 构建归一化邻接矩阵 Ã = D^{-1/2} A D^{-1/2}
            adj_mat = self._build_normalized_adj(bvids, n)

            # 初始化/获取权重
            if self._W0 is None or len(self._W0) != self.FEATURE_DIM:
                self._W0 = self._init_weights(self.FEATURE_DIM, hidden_dim)
                self._b0 = [0.0] * hidden_dim
            if self._W1 is None or len(self._W1) != hidden_dim:
                self._W1 = self._init_weights(hidden_dim, embed_dim)
                self._b1 = [0.0] * embed_dim

            # Layer 0: H1 = ReLU(Ã · X · W0 + b0)
            # Ã · X  ->  (n × n) × (n × d) = n × d
            AX = [self._adj_mat_vec_mul(adj_mat, X[i], n) for i in range(n)]
            # XW0 + b0  ->  (n × d) × (d × h) + h = n × h
            H1 = []
            for i in range(n):
                h_raw = [sum(AX[i][j] * self._W0[j][k] for j in range(self.FEATURE_DIM)) + self._b0[k]
                         for k in range(hidden_dim)]
                H1.append([_relu(x) for x in h_raw])

            # Layer 1: H2 = Ã · H1 · W1 + b1  (无激活，直接输出)
            AH1 = [self._adj_mat_vec_mul(adj_mat, H1[i], n) for i in range(n)]
            H2 = []
            for i in range(n):
                h_raw = [sum(AH1[i][j] * self._W1[j][k] for j in range(hidden_dim)) + self._b1[k]
                         for k in range(embed_dim)]
                H2.append(h_raw)

            self._embeddings = {bv: H2[i] for i, bv in enumerate(bvids)}
            return self._embeddings

    def get_node_features(self, bvid: str,
                          embeddings: Optional[Dict[str, List[float]]] = None) -> List[float]:
        """获取某视频的图增强特征（自身特征 + 邻居聚合特征 + GCN嵌入）。

        Returns
        -------
        list[float] : 拼接后的特征向量
        """
        with self._lock:
            own = self._features.get(bvid, [0.0] * self.FEATURE_DIM)

            # 邻居聚合特征（加权平均邻居特征）
            neighbors = self._adj.get(bvid, {})
            if neighbors:
                nb_feats = []
                total_w = 0.0
                for nb, w in neighbors.items():
                    f = self._features.get(nb, [0.0] * self.FEATURE_DIM)
                    nb_feats.append(f)
                    total_w += w
                agg = [0.0] * self.FEATURE_DIM
                if total_w > 0:
                    for f in nb_feats:
                        w = self._adj[bvid].get(
                            self._bvid_list[nb_feats.index(f)] if f in nb_feats else '', 0
                        )
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

    def get_graph_stats(self) -> Dict:
        """获取图结构统计信息。"""
        with self._lock:
            total_edges = sum(len(nb) for nb in self._adj.values()) // 2
            degrees = [len(self._adj.get(bv, {})) for bv in self._bvid_list]
            avg_degree = sum(degrees) / len(degrees) if degrees else 0
            max_degree = max(degrees) if degrees else 0
            return {
                'num_nodes': len(self._bvid_list),
                'num_edges': total_edges,
                'avg_degree': round(avg_degree, 2),
                'max_degree': max_degree,
                'feature_dim': self.FEATURE_DIM,
            }

    # ── 内部方法 ──────────────────────────────────

    def _extract_features(self, info: Dict) -> List[float]:
        """从视频信息提取 12 维特征向量。"""
        views = max(info.get('view_count', 0), 1)
        likes = info.get('like_count', 0) or 0
        coins = info.get('coin_count', 0) or 0
        shares = info.get('share_count', 0) or 0
        favs = info.get('favorite_count', 0) or 0
        danmaku = info.get('danmaku_count', 0) or 0
        replies = info.get('reply_count', 0) or 0
        viewers = info.get('viewers_total', 0) or 0
        duration = max(info.get('duration', 0), 1)

        return [
            math.log10(max(views, 1)),              # 1. 播放量对数
            likes / views,                          # 2. 点赞率
            coins / views,                          # 3. 投币率
            shares / views,                         # 4. 分享率
            favs / views,                           # 5. 收藏率
            danmaku / views,                        # 6. 弹幕率
            replies / views,                        # 7. 评论率
            viewers / max(views, 1),                # 8. 在线率
            math.log10(max(duration, 1)),           # 9. 时长对数
            (likes + coins + favs + shares) / views, # 10. 综合互动率
            coins / max(likes, 1),                  # 11. 投币/点赞比
            danmaku / max(replies, 1),              # 12. 弹幕/评论比
        ]

    def _compute_edge_weight(self, a: Dict, b: Dict) -> float:
        """计算两个视频之间的边权重 [0, 1]。"""
        w = 0.0
        count = 0

        # 1. 同UP主 (强关联)
        if a.get('owner_name') and b.get('owner_name'):
            if a['owner_name'] == b['owner_name']:
                w += 0.5
            count += 1

        # 2. 发布时间接近（48h内）
        pa = a.get('pubdate', '')
        pb = b.get('pubdate', '')
        if pa and pb:
            try:
                ta = datetime.fromisoformat(str(pa)).timestamp() if isinstance(pa, str) else float(pa)
                tb = datetime.fromisoformat(str(pb)).timestamp() if isinstance(pb, str) else float(pb)
                dt_hours = abs(ta - tb) / 3600.0
                if dt_hours < 48:
                    w += 0.3 * (1 - dt_hours / 48)
                count += 1
            except Exception:
                pass

        # 3. 互动率相似度
        va = max(a.get('view_count', 0), 1)
        vb = max(b.get('view_count', 0), 1)
        eng_a = (a.get('like_count', 0) or 0) / va
        eng_b = (b.get('like_count', 0) or 0) / vb
        eng_diff = abs(eng_a - eng_b)
        w += 0.2 * max(0, 1 - eng_diff * 100)
        count += 1

        if count == 0:
            return 0.0
        return min(1.0, w / count)

    def _build_normalized_adj(self, bvids: List[str], n: int) -> Dict[int, Dict[int, float]]:
        """构建 D^{-1/2} A D^{-1/2} 归一化邻接矩阵（稀疏字典形式）。

        Returns: sparse_adj[i][j] = weight
        """
        # 度数
        degree = [0.0] * n
        idx = {bv: i for i, bv in enumerate(bvids)}
        for bi in bvids:
            i = idx[bi]
            for bj, w in self._adj.get(bi, {}).items():
                if bj in idx:
                    degree[i] += w

        # D^{-1/2}
        d_inv_sqrt = [0.0] * n
        for i in range(n):
            d_inv_sqrt[i] = 1.0 / math.sqrt(max(degree[i], 1e-10))

        # Ã = D^{-1/2} A D^{-1/2} （加自环）
        adj: Dict[int, Dict[int, float]] = defaultdict(dict)
        for bi in bvids:
            i = idx[bi]
            # 自环
            adj[i][i] = 1.0
            for bj, w in self._adj.get(bi, {}).items():
                if bj in idx:
                    j = idx[bj]
                    adj[i][j] = d_inv_sqrt[i] * w * d_inv_sqrt[j]

        return dict(adj)

    def _adj_mat_vec_mul(self, adj: Dict[int, Dict[int, float]],
                         vec: List[float], n: int) -> List[float]:
        """稀疏矩阵 × 向量"""
        result = [0.0] * n
        for i, row in adj.items():
            s = 0.0
            for j, w in row.items():
                if j < len(vec):
                    s += w * vec[j]
            result[i] = s
        return result

    @staticmethod
    def _init_weights(in_dim: int, out_dim: float) -> List[List[float]]:
        """Xavier 初始化权重矩阵"""
        std = math.sqrt(2.0 / (in_dim + out_dim))
        import random
        return [[random.gauss(0, std) for _ in range(out_dim)] for _ in range(in_dim)]


# ── 全局单例 ────────────────────────────────────────
_global_graph: Optional[VideoGraph] = None
_graph_lock = threading.Lock()


def get_video_graph() -> VideoGraph:
    """获取全局 VideoGraph 单例。"""
    global _global_graph
    with _graph_lock:
        if _global_graph is None:
            _global_graph = VideoGraph()
        return _global_graph
