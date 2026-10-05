SUMMARY = "RTCS PL G1 read-only UIO control"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://rtcs_pl_g1.c"
S = "${WORKDIR}"

do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c11 -Wall -Wextra -Werror -o rtcs-pl-g1 rtcs_pl_g1.c
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 rtcs-pl-g1 ${D}${bindir}/rtcs-pl-g1
}
