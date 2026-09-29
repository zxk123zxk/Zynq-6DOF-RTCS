SUMMARY = "HX-30HM BusLinker USB read-only G1 protocol probe"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://rtcs_buslinker_g1.c file://g1_readonly_check.sh"
S = "${WORKDIR}"

do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c11 -Wall -Wextra -Werror -o rtcs-buslinker-g1 rtcs_buslinker_g1.c
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 rtcs-buslinker-g1 ${D}${bindir}/rtcs-buslinker-g1
    install -m 0755 g1_readonly_check.sh ${D}${bindir}/rtcs-g1-readonly-check
}
