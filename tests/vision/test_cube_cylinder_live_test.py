# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from src.vision.cube_cylinder_live_test import FrameProcessor, background_bgr_from_empty_image, parse_roi
from src.vision.cube_cylinder_pipeline import BackgroundDifferenceMaskConfig, GeometryClassifierConfig, OpenCVGeometryDetector

class LiveToolTest(unittest.TestCase):
    def test_roi_parser(self): self.assertEqual(parse_roi("10,20,110,220"),(10,20,110,220))
    def test_background_must_come_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"empty.png"; image=np.full((40,60,3),(20,40,60),np.uint8); cv2.imencode(".png",image)[1].tofile(p)
            self.assertEqual(background_bgr_from_empty_image(p,None),(20,40,60))
    def test_opencv_multiple_objects_and_global_roi_coordinates(self):
        image=np.full((240,360,3),(20,20,20),np.uint8); cv2.rectangle(image,(80,80),(130,130),(230,230,230),-1); cv2.circle(image,(240,105),26,(230,230,230),-1)
        detector=OpenCVGeometryDetector(BackgroundDifferenceMaskConfig((20,20,20),30,3),GeometryClassifierConfig(min_area_px2=200,max_area_px2=5000,min_side_px=10,max_side_px=100))
        processor=FrameProcessor("opencv",(40,40,320,180),opencv_detector=detector); outputs,_=processor.process(image,0,None,"still_image")
        self.assertEqual([d.class_name for d in outputs["opencv"].detections],["cube","cylinder"]); self.assertGreater(outputs["opencv"].detections[0].center_px[0],70)
    def test_empty_frame_has_empty_list(self):
        image=np.full((100,100,3),(20,20,20),np.uint8); detector=OpenCVGeometryDetector(BackgroundDifferenceMaskConfig((20,20,20),30,3))
        outputs,_=FrameProcessor("opencv",None,opencv_detector=detector).process(image,0,None,"still_image"); self.assertEqual(outputs["opencv"].detections,())

if __name__=="__main__": unittest.main()
