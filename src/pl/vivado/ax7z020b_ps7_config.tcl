# AX7Z020B PS7 settings derived from the board manual, not from a board preset.
# The manual identifies two 2 Gb x16 DDR3 devices (512 MiB total) and a
# 33.333333 MHz PS clock.  `MT41K128M16 JT-125` is the closest 2 Gb preset
# available in Vivado 2023.2; the physical power-on/DDR test remains G0 work.
proc apply_ax7z020b_ps7_config {ps7_cell} {
  set_property -dict [list \
    CONFIG.PCW_DDR_RAM_HIGHADDR {0x1FFFFFFF} \
    CONFIG.PCW_UIPARAM_DDR_FREQ_MHZ {533.333333} \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K128M16 JT-125} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_CLK0_FREQ {100000000} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
    CONFIG.PCW_EN_UART1 {1} \
    CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_UART1_UART1_IO {MIO 48 .. 49} \
    CONFIG.PCW_UART1_BAUD_RATE {115200} \
    CONFIG.PCW_UART1_GRP_FULL_ENABLE {0} \
    CONFIG.PCW_EN_SDIO0 {1} \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_SD0_GRP_CD_ENABLE {1} \
    CONFIG.PCW_SD0_GRP_CD_IO {MIO 47} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR {1} \
    CONFIG.PCW_IRQ_F2P_MODE {DIRECT} \
  ] [get_bd_cells $ps7_cell]
}
