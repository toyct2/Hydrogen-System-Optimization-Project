# Licensing scope and third-party attributions

The repository's **original Python source code and associated original documentation** are offered under the MIT License in [LICENSE](LICENSE), to the extent the repository maintainer holds the relevant rights. The MIT License **does not relicense third-party input datasets, publications, or any third-party material**. Such materials retain their original rights and license conditions.

## Research references

- Schmidhalter, I. et al. (2025), *Optimal green ammonia system design for minimum levelized costs in Southern Argentina*, International Journal of Hydrogen Energy. DOI: https://doi.org/10.1016/j.ijhydene.2025.03.317 . The plant and economic model reference in this repository is attributed to this paper.
- Smith, C. and Torrente-Murciano, L. (2025), *Cost efficiency versus energy utilization in green ammonia production from intermittent renewable energy*, Nature Chemical Engineering. DOI: https://doi.org/10.1038/s44286-025-00207-9 . The benchmark location/year and renewable profile preprocessing approach are informed by this work.
- Cambridge public MATLAB code: https://github.com/cjs227/CostEffvsEnUt . The repository and associated University of Cambridge Apollo code deposit (https://doi.org/10.17863/CAM.111760) identify MIT licensing. If any specific code expression is reused from this source, its original copyright and permission notice must be preserved. The present repository's Python implementation is not represented as an official release by either research group.

## Third-party renewable input datasets

- `data/benchmark_cambridge/pvgis_35.5_-0.5_2013_v52.json`: PVGIS 5.2 output using the PVGIS-SARAH2 dataset, via the European Commission Joint Research Centre. Source: https://re.jrc.ec.europa.eu/ . Credit: PVGIS © European Communities. Refer to original PVGIS and underlying data-provider terms for re-use.
- `data/benchmark_cambridge/newa_35.5_-0.5_2013.nc`: wind data obtained from the **New European Wind Atlas**, developed, owned and operated by the NEWA Consortium. Source: https://map.neweuropeanwindatlas.eu/ . NEWA's stated default terms license its works under Creative Commons Attribution 4.0 International (CC BY 4.0), unless otherwise indicated. Required credit: “Data obtained from the New European Wind Atlas, a free, web-based application developed, owned and operated by the NEWA Consortium. For additional information see www.neweuropeanwindatlas.eu.” License: https://creativecommons.org/licenses/by/4.0/ .
- The benchmark data package published by Cambridge at https://doi.org/10.17863/CAM.111758 lists **CC BY-NC 4.0**, unlike its MIT-licensed source code. This repository describes its data files as separately downloaded PVGIS/NEWA inputs, not Cambridge's benchmark data archive. If Cambridge archive materials are later incorporated, their distinct license must be respected.

See [data provenance and transformations](data/benchmark_cambridge/README.md) for details. Users should separately verify applicable data-provider conditions for further distribution or commercial re-use.
