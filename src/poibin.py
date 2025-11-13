# -*- coding: utf-8 -*-
from typing import List

def poisson_binomial_pmf(ps: List[float]):
    n = len(ps)
    pmf = [1.0] + [0.0] * n
    for p in ps:
        for k in range(n, 0, -1):
            pmf[k] = pmf[k] * (1 - p) + pmf[k-1] * p
        pmf[0] *= (1 - p)
    return pmf

def prob_at_least(ps: List[float], threshold: int):
    pmf = poisson_binomial_pmf(ps)
    return sum(pmf[threshold:])

def expected_shortfall(ps: List[float], target: int):
    pmf = poisson_binomial_pmf(ps)
    es = 0.0
    for k, prob in enumerate(pmf):
        short = max(target - k, 0)
        es += short * prob
    return es
