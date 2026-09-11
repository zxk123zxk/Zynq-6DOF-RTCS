SUMMARY = "AX7Z020B PS UART1 Linux smoke test"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://rtcs_uart_smoke.c"
S = "${WORKDIR}"

do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c11 -Wall -Wextra -Werror -o rtcs-uart-smoke rtcs_uart_smoke.c
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 rtcs-uart-smoke ${D}${bindir}/rtcs-uart-smoke
}
