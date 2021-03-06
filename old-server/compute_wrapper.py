import sys

# Copied from https://stackoverflow.com/questions/4103773/efficient-way-of-having-a-function-only-execute-once-in-a-loop
def run_once(f):
    def wrapper(*args, **kwargs):
        if not wrapper.has_run:
            wrapper.has_run = True
            print(f'Running {f.__name__}')
            return f(*args, **kwargs)
    wrapper.has_run = False
    return wrapper

@run_once
def import_compute():
    EXPT_DIR="./compute/"
    sys.path.append(EXPT_DIR)
    from core import config
    config.set_root_dir(EXPT_DIR)
    print("Imported compute submodule")

import_compute()
from core import get_test_results as expt
get_test_results = expt.get_test_results
get_matrix_sizes_and_labels = expt.get_matrix_sizes_and_labels
get_matrix_labels_and_matrices = expt.get_matrix_labels_and_matrices
get_matrix_codenames = expt.get_matrix_codenames
