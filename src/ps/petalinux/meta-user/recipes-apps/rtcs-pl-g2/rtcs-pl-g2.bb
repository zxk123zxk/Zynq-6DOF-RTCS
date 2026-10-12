SUMMARY = "RTCS PL G2 ABI 14 explicit single-axis and six-axis UIO control"
PR = "r6"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://rtcs_pl_g2.c file://rtcs_pl_g2_six.c file://rtcs_servo_diag.h"
S = "${WORKDIR}"

do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c11 -Wall -Wextra -Werror -o rtcs-pl-g2 rtcs_pl_g2.c
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c11 -Wall -Wextra -Werror -o rtcs-pl-g2-six rtcs_pl_g2_six.c
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 rtcs-pl-g2 ${D}${bindir}/rtcs-pl-g2
    install -m 0755 rtcs-pl-g2-six ${D}${bindir}/rtcs-pl-g2-six
}
