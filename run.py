"""
B站监控启动脚本
使用conda bilibili虚拟环境
"""

import sys
import os
import subprocess
import hashlib


# ── 源码完整性校验（与 main.py 共享同一逻辑）──
# 必须在任何应用模块导入之前执行
def _verify_source_integrity() -> None:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):
        project_root = os.path.dirname(sys.executable)

    devmode_hash = "40175C25B9517A906FCF778E50387017BB8FA6121D28EBD0720474E85EE7ECA8"
    for name in (".devmode", "devmode"):
        dp = os.path.join(project_root, name)
        if os.path.isfile(dp):
            try:
                with open(dp, "r", encoding="utf-8") as f:
                    if hashlib.sha256(f.read().strip().encode()).hexdigest().upper() == devmode_hash:
                        return
            except Exception:
                pass

    # 哈希值与 main.py 完全一致，以 main.py 为准
    integrity_hashes = {
        "core/bilibili_api.py": "53E89671FF3024E282C6CECB8A0D2D0B714D9949E4788EAE7A1973D6718D4BA6",
        "algorithms/registry.py": "69E9982411ED9A4DEF95B6C2C197B9EB42FD28775763550258D32B4D446EA77E",
        "algorithms/base.py": "C93D499D9BAF3C1A74C5BBF489F3221BA1EF63368561FEF851143D895F959258",
        "core/notification.py": "8B48903EDDFE10483486B741422913EA9CB6B4A77BE8885D1937DA4B16CB88BA",
    }

    for rel_path, expected_hash in integrity_hashes.items():
        filepath = os.path.join(project_root, rel_path)
        if not os.path.isfile(filepath):
            raise RuntimeError(
                f"文件缺失: {rel_path}\n\n"
                f"请执行 git restore 还原源文件，或创建 .devmode 文件跳过校验。\n"
                f"参考 README.md 文件"
            )
        with open(filepath, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest().upper()
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"文件已被篡改: {rel_path}\n"
                f"  预期: {expected_hash}\n"
                f"  实际: {actual_hash}\n\n"
                f"请执行 git restore 还原源文件，或创建 .devmode 文件跳过校验。\n"
                f"参考 README.md 文件"
            )


_verify_source_integrity()


def check_conda_env():
    """检查是否在正确的 conda 环境中（检测路径是否包含 bilibili/bili）"""
    current_python = sys.executable
    print(f"当前Python: {current_python}")

    if "bilibili" in current_python.lower() or "bili" in current_python.lower():
        print("✅ 已检测到bilibili/bili虚拟环境")
        return True

    print("⚠️ 未在bilibili虚拟环境中")
    print("尝试激活环境...")
    return False


def install_requirements():
    """安装 requirements.txt 中的依赖"""
    req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    print("\n📦 检查依赖...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_path], timeout=120)
        print("✅ 依赖安装完成")
        return True
    except subprocess.TimeoutExpired:
        print("❌ 依赖安装超时")
        return False
    except Exception as e:
        print(f"❌ 依赖安装失败: {e}")
        return False


def init_algorithms():
    """初始化算法模块：注册算法 → 检查高级模块"""
    print("\n🔧 初始化算法模块...")
    try:
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()

        algo_names = AlgorithmRegistry.get_algorithm_names()
        print(f"✅ 已加载 {len(algo_names)} 个预测算法:")
        for name in algo_names[:5]:
            print(f"   - {name}")
        if len(algo_names) > 5:
            print(f"   ... 还有 {len(algo_names) - 5} 个算法")

        # 检查各高级模块的可导入性
        try:
            from algorithms.online_learner import get_online_learner  # noqa: F401

            print("✅ 在线学习模块已加载")
        except ImportError:
            print("⚠️ 在线学习模块未找到")

        try:
            from algorithms.causal_inference import get_causal_analyzer  # noqa: F401

            print("✅ 因果推断模块已加载")
        except ImportError:
            print("⚠️ 因果推断模块未找到")

        try:
            from algorithms.graph_neural import get_video_graph  # noqa: F401

            print("✅ 图神经网络模块已加载")
        except ImportError:
            print("⚠️ 图神经网络模块未找到")

        return True
    except Exception as e:
        print(f"❌ 算法初始化失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """主函数：环境检查 → 安装依赖 → 初始化算法 → 启动 GUI"""
    print("=" * 50)
    print("B站视频监控与播放量预测系统")
    print("=" * 50)

    in_env = check_conda_env()
    if not in_env:
        print("\n请手动激活conda环境后运行:")
        print("conda activate bilibili")
        print("python run.py")
        print("\n或直接使用:")
        print("conda run -n bilibili python run.py")
        return

    if not install_requirements():
        response = input("依赖安装失败，是否继续? (y/n): ")
        if response.lower() != "y":
            return

    if not init_algorithms():
        response = input("算法初始化失败，是否继续? (y/n): ")
        if response.lower() != "y":
            return

    print("\n🚀 启动系统...")
    try:
        from ui.main_gui import main

        main()
    except ImportError as e:
        print(f"❌ 启动失败: {e}")
        print("请确保所有文件已正确下载")
    except Exception as e:
        print(f"❌ 运行错误: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
