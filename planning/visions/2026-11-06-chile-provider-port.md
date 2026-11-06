# Chile provider port

Deliver faithful, verified and documented access to Chilean river-gauge data through RivRetrieve. [The coordination hub](https://github.com/RivRetrieve/RivRetrieve/issues/734) owns the port and links its Efforts. This vision records the agreed port boundaries; publishing it does not complete the hub or any Effort. Resume each Effort through its discussion before implementing its unresolved scope.

## Scope and starting evidence

DGA/CR2 is the starting route, not a fixed implementation or final product scope. Step 1 establishes the supported source, geography, products, access and terms. The [historical investigation](https://github.com/RivRetrieve/RivRetrieve/issues/336) and its legacy and hydrodownloadR references are leads to recheck. Earlier observations include daily discharge through CR2, a separate DGA active-station workbook with incomplete overlap, leading-zero station identifiers and relative export URLs. They are not current verification evidence.

Establish source meaning rather than inheriting adapter conventions. In particular, the meaning of `minFrac: 80`, daily temporal support and time zone remain unresolved. A station listing does not establish observation availability. Preserve unknowns where the engine can represent them honestly; pause affected capabilities where proceeding requires guessing.

## Work and dependencies

Follow the [provider-port guide](../../docs/maintenance/provider-ports.md) and its existing evidence, testing and documentation processes:

1. [Source, scope and access](https://github.com/RivRetrieve/RivRetrieve/issues/739)
2. [Station catalogue and metadata](https://github.com/RivRetrieve/RivRetrieve/issues/736)
3. [Series identity and physical meaning](https://github.com/RivRetrieve/RivRetrieve/issues/740)
4. [Retrieval behavior](https://github.com/RivRetrieve/RivRetrieve/issues/735)
5. [Provider integration](https://github.com/RivRetrieve/RivRetrieve/issues/741)
6. [Verification](https://github.com/RivRetrieve/RivRetrieve/issues/742)
7. [User documentation](https://github.com/RivRetrieve/RivRetrieve/issues/737)
8. [Final review](https://github.com/RivRetrieve/RivRetrieve/issues/738)

Source scope establishes the baseline. Catalogue, physical meaning and retrieval inform integration; verification and user documentation finish against the complete integration. Evidence, tests and documentation develop throughout, and later findings can reopen earlier conclusions. Keep one continuing private research record in `verification-evidence`; public issues contain safe summaries and links rather than controlled material.

## Required CAMELS-CL comparison

Step 6 includes a comparison of public-API retrieval with **10 CAMELS-CL basins**. Select reproducibly at random among confidently matched gauges with overlapping dates, without choosing for agreement. Retain the dataset version, station and date selection, comparison method, hydrograph plots, findings and limitations through the existing evidence process. Preserve gaps, make unit conversions explicit and investigate meaningful discrepancies without shifting, filtering or fitting values to force agreement. If ten suitable matches or required inputs cannot be obtained, report the acceptance blocker rather than silently shrinking the sample.

The [published CAMELS-CL dataset](https://doi.pangaea.de/10.1594/PANGAEA.894885) contains 516 catchments with daily streamflow. Its [paper, section 3.1.5](https://hess.copernicus.org/articles/22/5817/2018/), identifies DGA via CR2 as the streamflow source. This comparison checks retrieval and processing consistency, not independent measurement accuracy. It supplements genuine source verification and cannot replace missing mandatory evidence.

## Completion and review

Keep implementation, documentation and corrections on `port/cl-dga`. Final review begins only after all seven provider-port Efforts are closed and examines the complete integration, verification results and user documentation. The reviewer is not yet assigned. Merge the completed port into `main` only after that reviewer's explicit approval. Publication of this planning document into the port branch authorizes neither provider implementation nor a merge into `main`.

The port succeeds when the supported scope works through the public APIs, material source claims and behavior have the required evidence, the ten-basin comparison is accounted for, documentation matches delivered behavior, and final review approves the result. Detailed source scope, implementation mechanisms and the final reviewer remain for their respective Efforts; this plan does not preselect them.
