# Third-party license notes

This file records project-specific license audit notes for dependencies whose
metadata needs context beyond the primary package license.

## tqdm

- **Version observed:** 4.67.3 in `uv.lock`.
- **Dependency path:** optional `[embeddings]` extra via `tokenizers` →
  `huggingface-hub` → `tqdm`.
- **License metadata:** `MPL-2.0 AND MIT`.
- **Project note:** MPL-2.0 is file-level weak copyleft. Trade Trace does not
  modify or vendor `tqdm`; if that changes, modifications to `tqdm` files must
  be made available under MPL-2.0.

## docutils

- **Version observed:** 0.22.4 in `uv.lock`.
- **Dependency path:** dev-only transitive dependency via `twine` →
  `readme-renderer` → `docutils`.
- **License metadata context:** docutils metadata declares a GPL-3+ Emacs Lisp
  file (`tools/editors/emacs/rst.el`) in the source distribution. The installed
  wheel used by this environment does not include `rst.el`.
- **Verification:** `.venv/**/rst.el` glob returned no installed files.
- **Project note:** Trade Trace does not redistribute docutils or include
  `rst.el`; no additional code change is required for this dev-only transitive
  dependency.
