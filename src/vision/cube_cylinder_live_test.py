"""Independent cube/cylinder visual test tool for camera, video, or image directories."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：编排 Camera、视频或图片目录输入，并对照运行既有 YOLO A/OpenCV 检测器。
# 本模块只导出原始图像像素坐标；未做真实标定，因此不产生 Workspace 毫米坐标。
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import logging
from pathlib import Path
import time

import cv2
import numpy as np

from .cube_cylinder_pipeline import (
    BackgroundDifferenceMaskConfig, GeometryClassifierConfig, ObjectDetection,
    ObjectDetectionFrame, OpenCVGeometryDetector,
)
from .yolo_inference import IsolatedYoloInference

IMAGE_SUFFIXES={".jpg",".jpeg",".png",".bmp",".tif",".tiff",".webp"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
YOLO_A = PROJECT_ROOT / "models/vision/yolo_a_cube_cylinder_best.pt"

def read_image(path:Path)->np.ndarray:
    """读取本地图片并返回 OpenCV BGR 数组；无法解码时抛出 ``ValueError``。"""
    image=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None: raise ValueError(f"无法读取图片: {path}")
    return image

def write_image(path:Path,image:np.ndarray)->None:
    """将 BGR 图像写入指定路径；编码失败时抛出 ``ValueError``。"""
    path.parent.mkdir(parents=True,exist_ok=True)
    ok,data=cv2.imencode(path.suffix,image)
    if not ok: raise ValueError(f"无法编码图片: {path}")
    data.tofile(path)

def parse_roi(text:str|None)->tuple[int,int,int,int]|None:
    """解析 ``x1,y1,x2,y2`` ROI；坐标单位为原始图像像素。"""
    if text is None: return None
    try: values=tuple(int(v.strip()) for v in text.split(","))
    except ValueError as exc: raise argparse.ArgumentTypeError("ROI必须为x1,y1,x2,y2整数") from exc
    if len(values)!=4 or values[0]<0 or values[1]<0 or values[2]<=values[0] or values[3]<=values[1]:
        raise argparse.ArgumentTypeError("ROI必须为有效的x1,y1,x2,y2")
    return values

def validate_roi(roi,width,height):
    """验证 ROI 位于宽 ``width``、高 ``height`` 的原图内，并返回有效范围。"""
    if roi is None:return (0,0,width,height)
    x1,y1,x2,y2=roi
    if x2>width or y2>height: raise ValueError(f"ROI {roi} 超出图像 {width}x{height}")
    return roi

def background_bgr_from_empty_image(path:Path,roi)->tuple[int,int,int]:
    """从独立空背景图的 ROI 计算 BGR 中位数，不使用含目标的当前帧替代背景。"""
    image=read_image(path); h,w=image.shape[:2]; x1,y1,x2,y2=validate_roi(roi,w,h)
    crop=image[y1:y2,x1:x2]
    return tuple(int(v) for v in np.median(crop.reshape(-1,3),axis=0))

class FrameProcessor:
    """调用已配置的检测后端，并把 ROI 局部结果恢复为原图像素坐标。

    ``mode`` 决定运行 YOLO A、实验性 OpenCV 几何检测器或二者对照。
    输出允许包含零到多个目标；空列表表示当前帧没有有效检测，绝不沿用旧帧坐标。
    """

    def __init__(self,mode,roi,yolo_engine=None,opencv_detector=None):
        """保存后端与 ROI；所选模式缺少对应后端时抛出 ``ValueError``。"""
        self.mode=mode; self.roi=roi; self.yolo=yolo_engine; self.opencv=opencv_detector
        if mode in {"yolo","compare"} and yolo_engine is None: raise ValueError("YOLO模式缺少engine")
        if mode in {"opencv","compare"} and opencv_detector is None: raise ValueError("OpenCV模式必须提供独立空背景图片")

    def process(self,frame,frame_index,timestamp_s,timestamp_kind):
        """处理一帧 BGR 图像，返回各后端的 ``ObjectDetectionFrame`` 与耗时。

        ``timestamp_s`` 的意义由 ``timestamp_kind`` 明确：视频使用媒体时间轴，Camera
        使用软件单调采集时刻，静态图片没有运动学时间戳。bbox 和 center 均恢复到
        原始输入图像的左上角原点像素坐标，x/u 向右、y/v 向下。
        """
        h,w=frame.shape[:2]; x1,y1,x2,y2=validate_roi(self.roi,w,h); crop=frame[y1:y2,x1:x2]
        outputs={}; timings={}
        if self.mode in {"yolo","compare"}:
            record,_=self.yolo.infer_frame(crop,source="live_test_roi",frame_index=frame_index,timestamp_s=timestamp_s,timestamp_kind=timestamp_kind)
            detections=[]
            for d in record.detections:
                bx1,by1,bx2,by2=d.bbox_xyxy
                detections.append(ObjectDetection(d.class_id,d.class_name,d.confidence,(bx1+x1,by1+y1,bx2+x1,by2+y1),(d.center_px[0]+x1,d.center_px[1]+y1),timestamp_s,True))
            outputs["yolo_a"]=ObjectDetectionFrame(frame_index,timestamp_s,timestamp_kind,w,h,tuple(detections))
            timings["yolo_inference_ms"]=record.processing_latency_s*1000
        if self.mode in {"opencv","compare"}:
            started=time.perf_counter(); local,_,_=self.opencv.detect(crop,frame_index=frame_index,timestamp_s=timestamp_s,timestamp_kind=timestamp_kind)
            detections=[ObjectDetection(d.class_id,d.class_name,d.confidence,(d.bbox_xyxy_px[0]+x1,d.bbox_xyxy_px[1]+y1,d.bbox_xyxy_px[2]+x1,d.bbox_xyxy_px[3]+y1),(d.center_px[0]+x1,d.center_px[1]+y1),timestamp_s,True) for d in local.detections]
            outputs["opencv"]=ObjectDetectionFrame(frame_index,timestamp_s,timestamp_kind,w,h,tuple(detections))
            timings["opencv_processing_ms"]=(time.perf_counter()-started)*1000
        return outputs,timings

def draw(frame,outputs,roi,timings,e2e_ms,fps):
    """在原图副本上绘制多目标结果、ROI 和性能信息，不改变检测结果。"""
    image=frame.copy(); colors={"yolo_a":(0,255,0),"opencv":(0,165,255)}
    if roi is not None: cv2.rectangle(image,(roi[0],roi[1]),(roi[2],roi[3]),(255,255,0),2)
    for backend,result in outputs.items():
        color=colors[backend]
        for d in result.detections:
            x1,y1,x2,y2=map(int,d.bbox_xyxy_px); u,v=d.center_px
            cv2.rectangle(image,(x1,y1),(x2,y2),color,2); cv2.circle(image,(round(u),round(v)),4,color,-1)
            score="YOLO conf" if backend=="yolo_a" else "geometry score"
            cv2.putText(image,f"{backend} {d.class_name} {score}={d.confidence:.2f} ({u:.1f},{v:.1f})",(x1,max(18,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1,cv2.LINE_AA)
    summary=" ".join(f"{k}={v:.1f}ms" for k,v in timings.items())
    cv2.putText(image,f"{summary} end-to-end={e2e_ms:.1f}ms FPS={fps:.1f}",(10,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),2,cv2.LINE_AA)
    if sum(len(v.detections) for v in outputs.values())==0: cv2.putText(image,"NO DETECTIONS",(10,52),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,0,255),2,cv2.LINE_AA)
    return image

def build_parser():
    """创建现有命令行解析器；默认阈值、权重和参数语义保持稳定。"""
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",choices=("camera","video","images"),required=True); p.add_argument("--input",type=Path)
    p.add_argument("--camera-index",type=int,default=0); p.add_argument("--mode",choices=("yolo","opencv","compare"),default="compare")
    p.add_argument("--weights",type=Path,default=YOLO_A); p.add_argument("--background",type=Path)
    p.add_argument("--roi",type=parse_roi); p.add_argument("--conf",type=float,default=.25); p.add_argument("--imgsz",type=int,default=640); p.add_argument("--device",default="0")
    p.add_argument("--background-distance",type=float,default=55.0); p.add_argument("--output-dir",type=Path,required=True); p.add_argument("--no-display",action="store_true")
    return p

def main(argv=None):
    """运行独立实时测试并保存 JSONL、可视化和摘要。

    Camera 时间戳来自 ``time.perf_counter``，不是硬件曝光时间；视频时间戳来自
    ``frame_index / FPS``。输出目录必须不存在，以避免覆盖历史证据。
    """
    args=build_parser().parse_args(argv)
    if args.output_dir.exists(): raise FileExistsError(f"拒绝覆盖已有输出目录: {args.output_dir}")
    args.output_dir.mkdir(parents=True); logging.basicConfig(filename=args.output_dir/"run.log",level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    if args.source!="camera" and (args.input is None or not args.input.exists()): raise FileNotFoundError("video/images模式必须提供有效--input")
    if args.mode in {"opencv","compare"} and (args.background is None or not args.background.is_file()): raise ValueError("OpenCV/compare模式必须用--background指定独立空背景图片")
    yolo=IsolatedYoloInference(args.weights,confidence=args.conf,imgsz=args.imgsz,device=args.device) if args.mode in {"yolo","compare"} else None
    opencv=None
    if args.mode in {"opencv","compare"}:
        bg=background_bgr_from_empty_image(args.background,args.roi)
        opencv=OpenCVGeometryDetector(BackgroundDifferenceMaskConfig(bg,args.background_distance,3),GeometryClassifierConfig())
    processor=FrameProcessor(args.mode,args.roi,yolo,opencv); records=[]; writer=None; cap=None
    if args.source=="images":
        paths=sorted(p for p in args.input.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        if not paths: raise ValueError("图片目录中没有支持的图片")
        iterator=((i,read_image(p),None,"still_image",p.name) for i,p in enumerate(paths)); fps_source=None
    else:
        source=args.camera_index if args.source=="camera" else str(args.input); cap=cv2.VideoCapture(source)
        if not cap.isOpened(): raise OSError(f"无法打开{args.source}: {source}")
        fps_source=float(cap.get(cv2.CAP_PROP_FPS)) if args.source=="video" else None
        def frames():
            i=0
            while True:
                ok,frame=cap.read()
                if not ok: break
                ts=i/fps_source if args.source=="video" and fps_source and fps_source>0 else time.perf_counter()
                yield i,frame,ts,"video_media_timeline" if args.source=="video" else "software_monotonic_capture",None; i+=1
        iterator=frames()
    jsonl=(args.output_dir/"detections.jsonl").open("w",encoding="utf-8"); last=time.perf_counter(); ema_fps=0.0
    try:
        for index,frame,timestamp,kind,name in iterator:
            started=time.perf_counter(); outputs,timings=processor.process(frame,index,timestamp,kind); elapsed=(time.perf_counter()-started)*1000
            now=time.perf_counter(); instantaneous=1/max(now-last,1e-9); ema_fps=instantaneous if index==0 else .9*ema_fps+.1*instantaneous; last=now
            annotated=draw(frame,outputs,args.roi,timings,elapsed,ema_fps)
            elapsed=(time.perf_counter()-started)*1000
            record={"frame_index":index,"timestamp_s":timestamp,"timestamp_kind":kind,"image_width_px":frame.shape[1],"image_height_px":frame.shape[0],"algorithms":{k:v.to_dict() for k,v in outputs.items()},"timing":{**timings,"end_to_end_processing_ms":elapsed,"display_loop_fps":ema_fps}}
            jsonl.write(json.dumps(record,ensure_ascii=False)+"\n"); jsonl.flush(); records.append(record)
            if args.source=="images": write_image(args.output_dir/"annotated_images"/(name or f"{index:06d}.png"),annotated)
            else:
                if writer is None:
                    rate=fps_source if fps_source and fps_source>0 else 30.0; writer=cv2.VideoWriter(str(args.output_dir/"annotated.mp4"),cv2.VideoWriter_fourcc(*"mp4v"),rate,(frame.shape[1],frame.shape[0]))
                    if not writer.isOpened(): raise OSError("无法创建输出视频")
                writer.write(annotated)
            if not args.no_display:
                cv2.imshow("Cube/Cylinder Visual Test - Q/Esc quit, S snapshot",annotated); key=cv2.waitKey(1)&0xFF
                if key in (ord("q"),27): break
                if key in (ord("s"),ord("S")): write_image(args.output_dir/f"snapshot_{index:06d}.png",annotated)
    finally:
        jsonl.close()
        if cap is not None: cap.release()
        if writer is not None: writer.release()
        cv2.destroyAllWindows()
    summary={"status":"complete","source":args.source,"mode":args.mode,"frames":len(records),"output":str(args.output_dir.resolve()),"millimetre_coordinates":False}
    (args.output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"); logging.info(json.dumps(summary,ensure_ascii=False)); print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
