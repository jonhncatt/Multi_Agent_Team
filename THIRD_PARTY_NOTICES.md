# Third-Party Notices

This project is licensed under the MIT License for repository-owned code. Third-party dependencies remain governed by their own licenses.

This notice is informational and is not legal advice. It was prepared from the dependency metadata available after installing:

```bash
python -m pip install -r requirements-dev.txt
```

The Python dependency list below covers direct dependencies declared in `requirements.txt` and `requirements-dev.txt`, plus the transitive dependency closure resolved in the local Python environment on 2026-06-10. Transitive versions may change if dependency constraints or package metadata change.

## License Summary

- MIT / BSD / Apache-2.0 style dependencies are permissive and do not change the license of repository-owned code.
- Apache-2.0 dependencies retain their own notice and patent terms; they do not require this project to become Apache-2.0.
- GPL / LGPL dependencies are listed separately because they can impose additional redistribution obligations when shipped as part of a combined distribution.
- The current direct runtime dependency set includes `extract-msg`, whose installed wheel includes GPL-3.0 license text.

## Direct Python Dependencies

| Package | Version | License metadata | Scope |
| --- | ---: | --- | --- |
| `fastapi` | 0.136.3 | MIT | runtime |
| `uvicorn` | 0.49.0 | BSD-3-Clause | runtime |
| `python-multipart` | 0.0.32 | Apache-2.0 | runtime |
| `openai` | 2.41.0 | Apache-2.0 | runtime |
| `langchain-openai` | 1.2.2 | MIT | runtime |
| `pydantic` | 2.13.4 | MIT | runtime |
| `pypdf` | 6.13.1 | BSD-3-Clause | runtime |
| `pdfplumber` | 0.11.9 | MIT | runtime |
| `python-docx` | 1.2.0 | MIT | runtime |
| `extract-msg` | 0.55.0 | GPL-3.0 license text in wheel | runtime, Outlook `.msg` parsing |
| `openpyxl` | 3.1.5 | MIT | runtime |
| `Pillow` | 12.2.0 | MIT-CMU | runtime |
| `pillow-heif` | 1.3.0 | BSD-3-Clause | runtime |
| `rapidocr-onnxruntime` | 1.4.4 | Apache-2.0 | runtime |
| `onnxruntime` | 1.26.0 | MIT | runtime |
| `playwright` | 1.60.0 | Apache-2.0 | runtime |
| `pytest` | 9.0.3 | MIT | development/test |

## Copyleft Python Dependencies

These packages were identified in the dependency closure and should be reviewed before distributing a bundled application or installer.

| Package | Version | License metadata | Relationship |
| --- | ---: | --- | --- |
| `extract-msg` | 0.55.0 | GPL, wheel includes GPL-3.0 license text | direct dependency for Outlook `.msg` parsing |
| `pcodedmp` | 1.2.6 | GPL, installed package includes GPL-3.0 license text | transitive dependency via `.msg` parsing stack |
| `RTFDE` | 0.1.2 | LGPLv3 license text | transitive dependency via `.msg` parsing stack |

No GPLv2 direct dependency was identified from the current `requirements*.txt` dependency closure. If an external scanner reports GPLv2, map the finding to the exact package and version before release decisions.

## Python Transitive Dependencies By License Family

### MIT Family

`annotated-doc`, `annotated-types`, `anyio`, `beautifulsoup4`, `cffi`, `charset-normalizer`, `colorclass`, `compressed-rtf`, `et-xmlfile`, `greenlet`, `h11`, `iniconfig`, `jiter`, `langchain-core`, `langchain-protocol`, `langsmith`, `lark`, `msoffcrypto-tool`, `openpyxl`, `pdfminer.six`, `pluggy`, `pyclipper`, `pydantic-core`, `pyee`, `pyparsing`, `PyYAML`, `red-black-tree-mod`, `six`, `soupsieve`, `tiktoken`, `tqdm`, `typing-inspection`, `tzlocal`, `urllib3`

### BSD Family

`click`, `easygui`, `ebcdic`, `httpcore`, `httpx`, `idna`, `jsonpatch`, `jsonpointer`, `lxml`, `olefile`, `oletools`, `pillow-heif`, `protobuf`, `pycparser`, `Pygments`, `pypdf`, `shapely`, `starlette`, `uvicorn`, `uuid-utils`, `zstandard`

### Apache-2.0 Family

`cryptography`, `distro`, `flatbuffers`, `openai`, `opencv-python`, `orjson`, `packaging`, `playwright`, `pypdfium2`, `python-multipart`, `rapidocr-onnxruntime`, `regex`, `requests`, `requests-toolbelt`, `sniffio`, `tenacity`

### Other / Additional Permissive Or File-Level Licenses

| Package | Version | License metadata |
| --- | ---: | --- |
| `certifi` | 2025.1.31 | MPL-2.0 |
| `numpy` | 1.26.4 | BSD-style license text in package metadata |
| `Pillow` | 12.2.0 | MIT-CMU |
| `typing-extensions` | 4.15.0 | PSF-2.0 |

## Vendored Frontend Assets

These files are committed into this repository under `app/static/vendor/` and are therefore included in source distributions.

| File | Upstream | License notice in file |
| --- | --- | --- |
| `app/static/vendor/react.production.min.js` | React | MIT |
| `app/static/vendor/react-dom.production.min.js` | React DOM; includes Modernizr custom build | MIT |
| `app/static/vendor/marked.umd.js` | marked 13.0.2 | MIT |
| `app/static/vendor/purify.min.js` | DOMPurify 3.1.6 | Apache-2.0 and MPL-2.0 |

## Practical Release Notes

- Keep the top-level `LICENSE` as MIT for repository-owned code.
- Preserve third-party license notices when redistributing source, wheels, installers, or bundled apps.
- If the product should remain free of GPL obligations in the default install path, move `.msg` support and `extract-msg` to an optional extra or separate requirements file.
- Re-run dependency license checks whenever `requirements.txt` or `requirements-dev.txt` changes.
