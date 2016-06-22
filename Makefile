#-----------------------------------------------------------------------------
# Makefile
#
# Project Name: product formatter
#-----------------------------------------------------------------------------
.PHONY: check-environment all install clean all-script install-script clean-script rpms

include make.config

all: all-script

install: check-environment install-script

clean: clean-script

#-----------------------------------------------------------------------------
all-script:
	echo "make all in scripts"; \
        (cd scripts; $(MAKE) all);

install-script:
	echo "make install in scripts"; \
        (cd scripts; $(MAKE) install);

clean-script:
	echo "make clean in scripts"; \
        (cd scripts; $(MAKE) clean);

#-----------------------------------------------------------------------------
rpms:
	rpmbuild -bb --clean RPM_spec_files/RPM.spec

#-----------------------------------------------------------------------------
check-environment:
ifndef PREFIX
    $(error Environment variable PREFIX is not defined)
endif

