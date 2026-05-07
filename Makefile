PYTHON ?= ./.venv/bin/python

.PHONY: clean test check-standalone-prereqs build-standalone smoke-standalone package-artifacts release-standalone

clean:
	rm -rf build/nuitka/standalone build/artifacts

test:
	$(PYTHON) -m pytest -q

check-standalone-prereqs:
	command -v patchelf >/dev/null
	$(PYTHON) -m nuitka --version >/dev/null

build-standalone:
	$(MAKE) check-standalone-prereqs
	bash scripts/build_nuitka_standalone.sh

smoke-standalone:
	bash scripts/smoke_nuitka_standalone.sh

package-artifacts:
	mkdir -p build/artifacts
	tar -C build/nuitka/standalone -czf build/artifacts/nexus-linux-x86_64.tar.gz nexus.dist

release-standalone: package-artifacts
	sha256sum build/artifacts/nexus-linux-x86_64.tar.gz > build/artifacts/nexus-linux-x86_64.tar.gz.sha256
