"""Create a tiny synthetic workflow input; refuse to overwrite existing files."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    target = Path(parser.parse_args().output)
    if target.exists():
        raise FileExistsError(target)
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy.sparse import csr_matrix
    rows, counts = [], []
    for donor in ('a', 'b', 'c'):
        for condition in ('ctrl', 'stim'):
            for cell in range(12):
                rows.append({'sample': donor + condition, 'donor': donor, 'condition': condition, 'cell_type': 'B cells'})
                counts.append([cell + 1, 3, 0])
    obs = pd.DataFrame(rows, index=['cell' + str(i) for i in range(len(rows))])
    matrix = csr_matrix(np.array(counts, dtype='int32'))
    data = ad.AnnData(X=matrix.copy(), obs=obs, var=pd.DataFrame(index=['gene_a', 'gene_b', 'filtered']))
    data.layers['counts'] = matrix
    data.uns['synthetic'] = True
    target.parent.mkdir(parents=True, exist_ok=True)
    data.write_h5ad(target)


if __name__ == '__main__':
    main()
