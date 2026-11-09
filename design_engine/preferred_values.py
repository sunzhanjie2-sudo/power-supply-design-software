"""Preferred nominal values for sizing. Component tolerances are checked separately."""
import math

E12 = (1., 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
E24 = (1., 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2., 2.2, 2.4, 2.7, 3., 3.3, 3.6,
       3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1)


def standard(value, series, up):
    decade = 10. ** math.floor(math.log10(value))
    choices = [round(m * decade, 16) for m in (series[-1]/10, *series, 10.)]
    if up:
        return next(x for x in choices if x >= value*(1-1e-12))
    return max(x for x in choices if x <= value*(1+1e-12))
