echo "RTCS G0: loading image.ub from SD"
fatload mmc 0:1 0x03000000 image.ub
bootm 0x03000000
