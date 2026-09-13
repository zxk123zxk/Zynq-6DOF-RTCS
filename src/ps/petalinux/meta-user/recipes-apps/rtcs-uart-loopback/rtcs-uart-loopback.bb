SUMMARY = "AX7Z020B PS UART serial loopback tool"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://rtcs_uart_loopback.c"
S = "${WORKDIR}"

do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c11 -Wall -Wextra -Werror -o rtcs-uart-loopback rtcs_uart_loopback.c
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 rtcs-uart-loopback ${D}${bindir}/rtcs-uart-loopback
}
