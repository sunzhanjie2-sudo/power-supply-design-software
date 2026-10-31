"""Process-local numeric resource defaults, before importing NumPy/SciPy.

The application solves small power-electronics systems, not large dense BLAS
jobs. Avoid reserving many native worker stacks for these tiny matrices. No
machine-wide settings are modified; explicit user library overrides win.
"""
import os


def configure_numeric_threads():
    raw=os.environ.get('POWER_DESIGN_NUM_THREADS','1')
    try:
        count=max(1,min(32,int(raw)))
    except (TypeError,ValueError):
        count=1
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS',
                'BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ.setdefault(key,str(count))
    return count
