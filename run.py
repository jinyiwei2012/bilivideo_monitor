"""
B站监控启动脚本
使用conda bilibili虚拟环境
"""
import sys
import subprocess
import os

def check_conda_env():
    """检查是否在正确的conda环境中"""
    # 获取当前Python路径
    current_python = sys.executable
    print(f"当前Python: {current_python}")
    
    # 检查是否包含bilibili或bili环境名
    if 'bilibili' in current_python.lower() or 'bili' in current_python.lower():
        print("✅ 已检测到bilibili/bili虚拟环境")
        return True
    
    print("⚠️ 未在bilibili虚拟环境中")
    print("尝试激活环境...")
    return False

def install_requirements():
    """安装依赖"""
    print("\n📦 检查依赖...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("✅ 依赖安装完成")
        return True
    except Exception as e:
        print(f"❌ 依赖安装失败: {e}")
        return False

def init_algorithms():
    """初始化算法模块"""
    print("\n🔧 初始化算法模块...")
    try:
        # 初始化算法注册器
        from algorithms.registry import AlgorithmRegistry
        AlgorithmRegistry.initialize()
        
        # 获取算法信息
        algo_names = AlgorithmRegistry.get_algorithm_names()
        print(f"✅ 已加载 {len(algo_names)} 个预测算法:")
        for name in algo_names[:5]:  # 只显示前5个
            print(f"   - {name}")
        if len(algo_names) > 5:
            print(f"   ... 还有 {len(algo_names) - 5} 个算法")
        
        # 检查高级模块
        try:
            from algorithms.online_learner import get_online_learner
            print("✅ 在线学习模块已加载")
        except ImportError:
            print("⚠️ 在线学习模块未找到")
        
        try:
            from algorithms.causal_inference import get_causal_analyzer
            print("✅ 因果推断模块已加载")
        except ImportError:
            print("⚠️ 因果推断模块未找到")
        
        try:
            from algorithms.graph_neural import get_video_graph
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
    """主函数"""
    print("=" * 50)
    print("B站视频监控与播放量预测系统")
    print("=" * 50)
    
    # 检查环境
    in_env = check_conda_env()
    
    if not in_env:
        print("\n请手动激活conda环境后运行:")
        print("conda activate bilibili")
        print("python run.py")
        print("\n或直接使用:")
        print("conda run -n bilibili python run.py")
        return
    
    # 安装依赖
    if not install_requirements():
        response = input("依赖安装失败，是否继续? (y/n): ")
        if response.lower() != 'y':
            return
    
    # 初始化算法模块
    if not init_algorithms():
        response = input("算法初始化失败，是否继续? (y/n): ")
        if response.lower() != 'y':
            return
    
    # 启动GUI
    print("\n🚀 启动系统...")
    try:
        from main_gui import main
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
