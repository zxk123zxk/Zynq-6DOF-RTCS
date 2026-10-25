# Cube/Cylinder 独立视觉模块 V1.1

本 Windows PC 模块用 YOLO11n 检测 Cube（0）与 Cylinder（1）。只输出原图像素坐标，不连接 Zynq 或机械臂，不提供抓取点或毫米坐标。模型训练背景、已知限制见 [MODEL_INFO.md](MODEL_INFO.md)。

## 文件结构

`models/best.pt` 为冻结权重；`vision/` 内分别是推理、相机、结果结构和绘图；`scripts/camera_demo.py`、`scripts/image_demo.py` 为入口；`integration/ps_payload.py` 只做结构转换；`tests/` 为自动测试。许可和署名见 `LICENSE-AGPL-3.0.txt`、`NOTICE.md`。

## Python 3.10.18 环境

在 Windows PowerShell 进入解压目录，先安装 Python 3.10.18 64 位，再检查 `py -3.10 --version`。如果 `py` 未注册，可把下述 `py -3.10` 换成 Python 3.10.18 的完整可执行文件路径。不要在 Anaconda base、LeRobot 等已有环境安装。

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\camera_demo.py --check-model
```

依赖锁定在 `requirements.txt`；CUDA 版 PyTorch 的安装来源依显卡驱动而定。若使用 NVIDIA GPU，可在安装 requirements **之前**，参考 [PyTorch 官方历史版本命令](https://pytorch.org/get-started/previous-versions/)安装匹配的 PyTorch 2.5.1 / torchvision 0.20.1 CUDA 构建。例如支持 CUDA 12.1 的环境：

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

没有 NVIDIA GPU 可直接安装 requirements 并使用 `--device cpu`。不需要 LeRobot、Vivado 或 Vitis。首次模型加载或推理可能较慢。

## USB 摄像头实时识别

连接摄像头，关闭其他占用设备的程序。在模块根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\camera_demo.py
```

默认摄像头编号 1、Windows DirectShow、请求 640×480、完整画面、`imgsz=640`、`conf=0.25`、GPU 可用时优先 GPU。实际分辨率由摄像头决定；不使用旧 ROI。窗口按 **Q** 退出。若设备编号不同：

```powershell
.\.venv\Scripts\python.exe scripts\camera_demo.py --camera-index 0 --backend dshow
.\.venv\Scripts\python.exe scripts\camera_demo.py --device cpu
```

保留 V1.0 参数：`--camera-index`、`--backend`、`--width`、`--height`、`--imgsz`、`--conf`、`--device`、`--check-model`、`--max-frames`。`--backend any` 或 `--backend msmf` 可用于诊断 DirectShow 打不开的问题。每帧标准输出 JSON 继续含 `frame_index`、`timestamp_monotonic_s`、`detections`，每个目标仍含类别、置信度、框、中心、实际帧宽高；无检测为 `[]`。FPS 是采集到显示的循环速度，不是独立推理耗时。

## 单图及 Python API

```powershell
.\.venv\Scripts\python.exe scripts\image_demo.py .\example.jpg --output .\example_annotated.jpg --device cpu
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

图片路径由使用者提供；包内不含测试图片。程序导入示例（从模块根目录运行）：

```python
import cv2
from vision import Detector
from integration import to_ps_payload

frame = cv2.imread("example.jpg")
result = Detector(device="cpu").detect(frame)
payload = to_ps_payload(result)
print(payload["detections"])
```

返回零到多个目标；`bbox_xyxy=[x1,y1,x2,y2]` 与中心均为原始图像像素。详细契约与无目标示例见 [INTEGRATION.md](INTEGRATION.md)。

## 常见问题

- `找不到模型`：保留 `models/best.pt` 和整个目录结构。
- `无法打开摄像头`：检查编号、Windows 摄像头权限、其他软件占用；尝试 `--backend any`。脚本不会自动选择可能错误的设备。
- CUDA 不可用：核查驱动与 CUDA 版 torch，或使用 `--device cpu`。
- 有目标却没有框：确认成像尺寸、清晰度、光照；模型曾出现 Cube→Cylinder 错分类，不能直接用于抓取。
- `py -3.10` 不可用：检查 Python 3.10.18 安装及 Python Launcher；使用 Python 的完整路径创建 venv。

本包的结果尚未完成跨场景独立验收、相机标定与抓取闭环验证。
