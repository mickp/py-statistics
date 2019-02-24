# -*- coding: UTF-8 -*-
u"""
Basic statistics module.

This module provides functions for calculating statistics of data, including
averages, variance, and standard deviation.

Calculating averages
--------------------

==================  =============================================
Function            Description
==================  =============================================
mean                Arithmetic mean (average) of data.
harmonic_mean       Harmonic mean of data.
median              Median (middle value) of data.
median_low          Low median of data.
median_high         High median of data.
median_grouped      Median, or 50th percentile, of grouped data.
mode                Mode (most common value) of data.
==================  =============================================

Calculate the arithmetic mean ("the average") of data:

>>> mean([-1.0, 2.5, 3.25, 5.75])
2.625


Calculate the standard median of discrete data:

>>> median([2, 3, 4, 5])
3.5


Calculate the median, or 50th percentile, of data grouped into class intervals
centred on the data values provided. E.g. if your data points are rounded to
the nearest whole number:

>>> median_grouped([2, 2, 3, 3, 3, 4])  #doctest: +ELLIPSIS
2.8333333333...

This should be interpreted in this way: you have two data points in the class
interval 1.5-2.5, three data points in the class interval 2.5-3.5, and one in
the class interval 3.5-4.5. The median of these data points is 2.8333...


Calculating variability or spread
---------------------------------

==================  =============================================
Function            Description
==================  =============================================
pvariance           Population variance of data.
variance            Sample variance of data.
pstdev              Population standard deviation of data.
stdev               Sample standard deviation of data.
==================  =============================================

Calculate the standard deviation of sample data:

>>> stdev([2.5, 3.25, 5.5, 11.25, 11.75])  #doctest: +ELLIPSIS
4.38961843444...

If you have previously calculated the mean, you can pass it as the optional
second argument to the four "spread" functions to avoid recalculating it:

>>> data = [1, 2, 2, 4, 4, 4, 5, 6]
>>> mu = mean(data)
>>> pvariance(data, mu)
2.5


Exceptions
----------

A single exception is defined: StatisticsError is a subclass of ValueError.

"""

from __future__ import division
__all__ = [ u'StatisticsError', u'NormalDist',
            u'pstdev', u'pvariance', u'stdev', u'variance',
            u'median',  u'median_low', u'median_high', u'median_grouped',
            u'mean', u'mode', u'harmonic_mean', u'fmean',
          ]

import collections
import math
import numbers
import random

from fractions import Fraction
from decimal import Decimal
from itertools import groupby
from bisect import bisect_left, bisect_right
from math import hypot, sqrt, fabs, exp, erf, pi
tau = 2 * pi



# === Exceptions ===

class StatisticsError(ValueError):
    pass


# === Private utilities ===

def _sum(data, start=0):
    u"""_sum(data [, start]) -> (type, sum, count)

    Return a high-precision sum of the given numeric data as a fraction,
    together with the type to be converted to and the count of items.

    If optional argument ``start`` is given, it is added to the total.
    If ``data`` is empty, ``start`` (defaulting to 0) is returned.


    Examples
    --------

    >>> _sum([3, 2.25, 4.5, -0.5, 1.0], 0.75)
    (<class 'float'>, Fraction(11, 1), 5)

    Some sources of round-off error will be avoided:

    # Built-in sum returns zero.
    >>> _sum([1e50, 1, -1e50] * 1000)
    (<class 'float'>, Fraction(1000, 1), 3000)

    Fractions and Decimals are also supported:

    >>> from fractions import Fraction as F
    >>> _sum([F(2, 3), F(7, 5), F(1, 4), F(5, 6)])
    (<class 'fractions.Fraction'>, Fraction(63, 20), 4)

    >>> from decimal import Decimal as D
    >>> data = [D("0.1375"), D("0.2108"), D("0.3061"), D("0.0419")]
    >>> _sum(data)
    (<class 'decimal.Decimal'>, Fraction(6963, 10000), 4)

    Mixed types are currently treated as an error, except that int is
    allowed.
    """
    count = 0
    n, d = _exact_ratio(start)
    partials = {d: n}
    partials_get = partials.get
    T = _coerce(int, type(start))
    for typ, values in groupby(data, type):
        T = _coerce(T, typ)  # or raise TypeError
        for n,d in map(_exact_ratio, values):
            count += 1
            partials[d] = partials_get(d, 0) + n
    if None in partials:
        # The sum will be a NAN or INF. We can ignore all the finite
        # partials, and just look at this special one.
        total = partials[None]
        assert not _isfinite(total)
    else:
        # Sum all the partial sums using builtin sum.
        # FIXME is this faster if we sum them in order of the denominator?
        total = sum(Fraction(n, d) for d, n in sorted(partials.items()))
    return (T, total, count)


def _isfinite(x):
    try:
        return x.is_finite()  # Likely a Decimal.
    except AttributeError:
        return math.isfinite(x)  # Coerces to float first.


def _coerce(T, S):
    u"""Coerce types T and S to a common type, or raise TypeError.

    Coercion rules are currently an implementation detail. See the CoerceTest
    test class in test_statistics for details.
    """
    # See http://bugs.python.org/issue24068.
    assert T is not bool, "initial type T is bool"
    # If the types are the same, no need to coerce anything. Put this
    # first, so that the usual case (no coercion needed) happens as soon
    # as possible.
    if T is S:  return T
    # Mixed int & other coerce to the other type.
    if S is int or S is bool:  return T
    if T is int:  return S
    # If one is a (strict) subclass of the other, coerce to the subclass.
    if issubclass(S, T):  return S
    if issubclass(T, S):  return T
    # Ints coerce to the other type.
    if issubclass(T, int):  return S
    if issubclass(S, int):  return T
    # Mixed fraction & float coerces to float (or float subclass).
    if issubclass(T, Fraction) and issubclass(S, float):
        return S
    if issubclass(T, float) and issubclass(S, Fraction):
        return T
    # Any other combination is disallowed.
    msg = "don't know how to coerce %s and %s"
    raise TypeError(msg % (T.__name__, S.__name__))


def _exact_ratio(x):
    u"""Return Real number x to exact (numerator, denominator) pair.

    >>> _exact_ratio(0.25)
    (1, 4)

    x is expected to be an int, Fraction, Decimal or float.
    """
    try:
        # Optimise the common case of floats. We expect that the most often
        # used numeric type will be builtin floats, so try to make this as
        # fast as possible.
        if type(x) is float or type(x) is Decimal:
            return x.as_integer_ratio()
        try:
            # x may be an int, Fraction, or Integral ABC.
            return (x.numerator, x.denominator)
        except AttributeError:
            try:
                # x may be a float or Decimal subclass.
                return x.as_integer_ratio()
            except AttributeError:
                # Just give up?
                pass
    except (OverflowError, ValueError):
        # float NAN or INF.
        assert not _isfinite(x)
        return (x, None)
    msg = u"can't convert type '{}' to numerator/denominator"
    raise TypeError(msg.format(type(x).__name__))


def _convert(value, T):
    u"""Convert value to given numeric type T."""
    if type(value) is T:
        # This covers the cases where T is Fraction, or where value is
        # a NAN or INF (Decimal or float).
        return value
    if issubclass(T, int) and value.denominator != 1:
        T = float
    try:
        # FIXME: what do we do if this overflows?
        return T(value)
    except TypeError:
        if issubclass(T, Decimal):
            return T(value.numerator)/T(value.denominator)
        else:
            raise


def _counts(data):
    # Generate a table of sorted (value, frequency) pairs.
    table = collections.Counter(iter(data)).most_common()
    if not table:
        return table
    # Extract the values with the highest frequency.
    maxfreq = table[0][1]
    for i in xrange(1, len(table)):
        if table[i][1] != maxfreq:
            table = table[:i]
            break
    return table


def _find_lteq(a, x):
    u'Locate the leftmost value exactly equal to x'
    i = bisect_left(a, x)
    if i != len(a) and a[i] == x:
        return i
    raise ValueError


def _find_rteq(a, l, x):
    u'Locate the rightmost value exactly equal to x'
    i = bisect_right(a, x, lo=l)
    if i != (len(a)+1) and a[i-1] == x:
        return i-1
    raise ValueError


def _fail_neg(values, errmsg='negative value'):
    u"""Iterate over values, failing if any are less than zero."""
    for x in values:
        if x < 0:
            raise StatisticsError(errmsg)
        yield x


# === Measures of central tendency (averages) ===

def mean(data):
    u"""Return the sample arithmetic mean of data.

    >>> mean([1, 2, 3, 4, 4])
    2.8

    >>> from fractions import Fraction as F
    >>> mean([F(3, 7), F(1, 21), F(5, 3), F(1, 3)])
    Fraction(13, 21)

    >>> from decimal import Decimal as D
    >>> mean([D("0.5"), D("0.75"), D("0.625"), D("0.375")])
    Decimal('0.5625')

    If ``data`` is empty, StatisticsError will be raised.
    """
    if iter(data) is data:
        data = list(data)
    n = len(data)
    if n < 1:
        raise StatisticsError(u'mean requires at least one data point')
    T, total, count = _sum(data)
    assert count == n
    return _convert(total/n, T)

def fmean(data):
    u""" Convert data to floats and compute the arithmetic mean.

    This runs faster than the mean() function and it always returns a float.
    The result is highly accurate but not as perfect as mean().
    If the input dataset is empty, it raises a StatisticsError.

    >>> fmean([3.5, 4.0, 5.25])
    4.25

    """
    try:
        n = len(data)
    except TypeError:
        # Handle iterators that do not define __len__().
        n = 0
        def count(x):
            n += 1
            return x
        total = math.fsum(map(count, data))
    else:
        total = math.fsum(data)
    try:
        return total / n
    except ZeroDivisionError:
        raise StatisticsError(u'fmean requires at least one data point')

def harmonic_mean(data):
    u"""Return the harmonic mean of data.

    The harmonic mean, sometimes called the subcontrary mean, is the
    reciprocal of the arithmetic mean of the reciprocals of the data,
    and is often appropriate when averaging quantities which are rates
    or ratios, for example speeds. Example:

    Suppose an investor purchases an equal value of shares in each of
    three companies, with P/E (price/earning) ratios of 2.5, 3 and 10.
    What is the average P/E ratio for the investor's portfolio?

    >>> harmonic_mean([2.5, 3, 10])  # For an equal investment portfolio.
    3.6

    Using the arithmetic mean would give an average of about 5.167, which
    is too high.

    If ``data`` is empty, or any element is less than zero,
    ``harmonic_mean`` will raise ``StatisticsError``.
    """
    # For a justification for using harmonic mean for P/E ratios, see
    # http://fixthepitch.pellucid.com/comps-analysis-the-missing-harmony-of-summary-statistics/
    # http://papers.ssrn.com/sol3/papers.cfm?abstract_id=2621087
    if iter(data) is data:
        data = list(data)
    errmsg = u'harmonic mean does not support negative values'
    n = len(data)
    if n < 1:
        raise StatisticsError(u'harmonic_mean requires at least one data point')
    elif n == 1:
        x = data[0]
        if isinstance(x, (numbers.Real, Decimal)):
            if x < 0:
                raise StatisticsError(errmsg)
            return x
        else:
            raise TypeError(u'unsupported type')
    try:
        T, total, count = _sum(1/x for x in _fail_neg(data, errmsg))
    except ZeroDivisionError:
        return 0
    assert count == n
    return _convert(n/total, T)


# FIXME: investigate ways to calculate medians without sorting? Quickselect?
def median(data):
    u"""Return the median (middle value) of numeric data.

    When the number of data points is odd, return the middle data point.
    When the number of data points is even, the median is interpolated by
    taking the average of the two middle values:

    >>> median([1, 3, 5])
    3
    >>> median([1, 3, 5, 7])
    4.0

    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError(u"no median for empty data")
    if n%2 == 1:
        return data[n//2]
    else:
        i = n//2
        return (data[i - 1] + data[i])/2


def median_low(data):
    u"""Return the low median of numeric data.

    When the number of data points is odd, the middle value is returned.
    When it is even, the smaller of the two middle values is returned.

    >>> median_low([1, 3, 5])
    3
    >>> median_low([1, 3, 5, 7])
    3

    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError(u"no median for empty data")
    if n%2 == 1:
        return data[n//2]
    else:
        return data[n//2 - 1]


def median_high(data):
    u"""Return the high median of data.

    When the number of data points is odd, the middle value is returned.
    When it is even, the larger of the two middle values is returned.

    >>> median_high([1, 3, 5])
    3
    >>> median_high([1, 3, 5, 7])
    5

    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError(u"no median for empty data")
    return data[n//2]


def median_grouped(data, interval=1):
    u"""Return the 50th percentile (median) of grouped continuous data.

    >>> median_grouped([1, 2, 2, 3, 4, 4, 4, 4, 4, 5])
    3.7
    >>> median_grouped([52, 52, 53, 54])
    52.5

    This calculates the median as the 50th percentile, and should be
    used when your data is continuous and grouped. In the above example,
    the values 1, 2, 3, etc. actually represent the midpoint of classes
    0.5-1.5, 1.5-2.5, 2.5-3.5, etc. The middle value falls somewhere in
    class 3.5-4.5, and interpolation is used to estimate it.

    Optional argument ``interval`` represents the class interval, and
    defaults to 1. Changing the class interval naturally will change the
    interpolated 50th percentile value:

    >>> median_grouped([1, 3, 3, 5, 7], interval=1)
    3.25
    >>> median_grouped([1, 3, 3, 5, 7], interval=2)
    3.5

    This function does not check whether the data points are at least
    ``interval`` apart.
    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError(u"no median for empty data")
    elif n == 1:
        return data[0]
    # Find the value at the midpoint. Remember this corresponds to the
    # centre of the class interval.
    x = data[n//2]
    for obj in (x, interval):
        if isinstance(obj, (unicode, str)):
            raise TypeError(u'expected number but got %r' % obj)
    try:
        L = x - interval/2  # The lower limit of the median interval.
    except TypeError:
        # Mixed type. For now we just coerce to float.
        L = float(x) - float(interval)/2

    # Uses bisection search to search for x in data with log(n) time complexity
    # Find the position of leftmost occurrence of x in data
    l1 = _find_lteq(data, x)
    # Find the position of rightmost occurrence of x in data[l1...len(data)]
    # Assuming always l1 <= l2
    l2 = _find_rteq(data, l1, x)
    cf = l1
    f = l2 - l1 + 1
    return L + interval*(n/2 - cf)/f


def mode(data):
    u"""Return the most common data point from discrete or nominal data.

    ``mode`` assumes discrete data, and returns a single value. This is the
    standard treatment of the mode as commonly taught in schools:

    >>> mode([1, 1, 2, 3, 3, 3, 3, 4])
    3

    This also works with nominal (non-numeric) data:

    >>> mode(["red", "blue", "blue", "red", "green", "red", "red"])
    'red'

    If there is not exactly one most common value, ``mode`` will raise
    StatisticsError.
    """
    # Generate a table of sorted (value, frequency) pairs.
    table = _counts(data)
    if len(table) == 1:
        return table[0][0]
    elif table:
        raise StatisticsError(
                u'no unique mode; found %d equally common values' % len(table)
                )
    else:
        raise StatisticsError(u'no mode for empty data')


# === Measures of spread ===

# See http://mathworld.wolfram.com/Variance.html
#     http://mathworld.wolfram.com/SampleVariance.html
#     http://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
#
# Under no circumstances use the so-called "computational formula for
# variance", as that is only suitable for hand calculations with a small
# amount of low-precision data. It has terrible numeric properties.
#
# See a comparison of three computational methods here:
# http://www.johndcook.com/blog/2008/09/26/comparing-three-methods-of-computing-standard-deviation/

def _ss(data, c=None):
    u"""Return sum of square deviations of sequence data.

    If ``c`` is None, the mean is calculated in one pass, and the deviations
    from the mean are calculated in a second pass. Otherwise, deviations are
    calculated from ``c`` as given. Use the second case with care, as it can
    lead to garbage results.
    """
    if c is None:
        c = mean(data)
    T, total, count = _sum((x-c)**2 for x in data)
    # The following sum should mathematically equal zero, but due to rounding
    # error may not.
    U, total2, count2 = _sum((x-c) for x in data)
    assert T == U and count == count2
    total -=  total2**2/len(data)
    assert not total < 0, u'negative sum of square deviations: %f' % total
    return (T, total)


def variance(data, xbar=None):
    u"""Return the sample variance of data.

    data should be an iterable of Real-valued numbers, with at least two
    values. The optional argument xbar, if given, should be the mean of
    the data. If it is missing or None, the mean is automatically calculated.

    Use this function when your data is a sample from a population. To
    calculate the variance from the entire population, see ``pvariance``.

    Examples:

    >>> data = [2.75, 1.75, 1.25, 0.25, 0.5, 1.25, 3.5]
    >>> variance(data)
    1.3720238095238095

    If you have already calculated the mean of your data, you can pass it as
    the optional second argument ``xbar`` to avoid recalculating it:

    >>> m = mean(data)
    >>> variance(data, m)
    1.3720238095238095

    This function does not check that ``xbar`` is actually the mean of
    ``data``. Giving arbitrary values for ``xbar`` may lead to invalid or
    impossible results.

    Decimals and Fractions are supported:

    >>> from decimal import Decimal as D
    >>> variance([D("27.5"), D("30.25"), D("30.25"), D("34.5"), D("41.75")])
    Decimal('31.01875')

    >>> from fractions import Fraction as F
    >>> variance([F(1, 6), F(1, 2), F(5, 3)])
    Fraction(67, 108)

    """
    if iter(data) is data:
        data = list(data)
    n = len(data)
    if n < 2:
        raise StatisticsError(u'variance requires at least two data points')
    T, ss = _ss(data, xbar)
    return _convert(ss/(n-1), T)


def pvariance(data, mu=None):
    u"""Return the population variance of ``data``.

    data should be an iterable of Real-valued numbers, with at least one
    value. The optional argument mu, if given, should be the mean of
    the data. If it is missing or None, the mean is automatically calculated.

    Use this function to calculate the variance from the entire population.
    To estimate the variance from a sample, the ``variance`` function is
    usually a better choice.

    Examples:

    >>> data = [0.0, 0.25, 0.25, 1.25, 1.5, 1.75, 2.75, 3.25]
    >>> pvariance(data)
    1.25

    If you have already calculated the mean of the data, you can pass it as
    the optional second argument to avoid recalculating it:

    >>> mu = mean(data)
    >>> pvariance(data, mu)
    1.25

    This function does not check that ``mu`` is actually the mean of ``data``.
    Giving arbitrary values for ``mu`` may lead to invalid or impossible
    results.

    Decimals and Fractions are supported:

    >>> from decimal import Decimal as D
    >>> pvariance([D("27.5"), D("30.25"), D("30.25"), D("34.5"), D("41.75")])
    Decimal('24.815')

    >>> from fractions import Fraction as F
    >>> pvariance([F(1, 4), F(5, 4), F(1, 2)])
    Fraction(13, 72)

    """
    if iter(data) is data:
        data = list(data)
    n = len(data)
    if n < 1:
        raise StatisticsError(u'pvariance requires at least one data point')
    T, ss = _ss(data, mu)
    return _convert(ss/n, T)


def stdev(data, xbar=None):
    u"""Return the square root of the sample variance.

    See ``variance`` for arguments and other details.

    >>> stdev([1.5, 2.5, 2.5, 2.75, 3.25, 4.75])
    1.0810874155219827

    """
    var = variance(data, xbar)
    try:
        return var.sqrt()
    except AttributeError:
        return math.sqrt(var)


def pstdev(data, mu=None):
    u"""Return the square root of the population variance.

    See ``pvariance`` for arguments and other details.

    >>> pstdev([1.5, 2.5, 2.5, 2.75, 3.25, 4.75])
    0.986893273527251

    """
    var = pvariance(data, mu)
    try:
        return var.sqrt()
    except AttributeError:
        return math.sqrt(var)

## Normal Distribution #####################################################

class NormalDist:
    u'Normal distribution of a random variable'
    # https://en.wikipedia.org/wiki/Normal_distribution
    # https://en.wikipedia.org/wiki/Variance#Properties

    __slots__ = ('mu', 'sigma')

    def __init__(self, mu=0.0, sigma=1.0):
        u'NormalDist where mu is the mean and sigma is the standard deviation'
        if sigma < 0.0:
            raise StatisticsError(u'sigma must be non-negative')
        self.mu = mu
        self.sigma = sigma

    @classmethod
    def from_samples(cls, data):
        u'Make a normal distribution instance from sample data'
        if not isinstance(data, (list, tuple)):
            data = list(data)
        xbar = fmean(data)
        return cls(xbar, stdev(data, xbar))

    def samples(self, n, seed=None):
        u'Generate *n* samples for a given mean and standard deviation'
        gauss = random.gauss if seed is None else random.Random(seed).gauss
        mu, sigma = self.mu, self.sigma
        return [gauss(mu, sigma) for i in range(n)]

    def pdf(self, x):
        u'Probability density function:  P(x <= X < x+dx) / dx'
        variance = self.sigma ** 2.0
        if not variance:
            raise StatisticsError(u'pdf() not defined when sigma is zero')
        return exp((x - self.mu)**2.0 / (-2.0*variance)) / sqrt(tau * variance)

    def cdf(self, x):
        u'Cumulative density function:  P(X <= x)'
        if not self.sigma:
            raise StatisticsError(u'cdf() not defined when sigma is zero')
        return 0.5 * (1.0 + erf((x - self.mu) / (self.sigma * sqrt(2.0))))

    @property
    def variance(self):
        u'Square of the standard deviation'
        return self.sigma ** 2.0

    def __add__(x1, x2):
        if isinstance(x2, NormalDist):
            return NormalDist(x1.mu + x2.mu, hypot(x1.sigma, x2.sigma))
        return NormalDist(x1.mu + x2, x1.sigma)

    def __sub__(x1, x2):
        if isinstance(x2, NormalDist):
            return NormalDist(x1.mu - x2.mu, hypot(x1.sigma, x2.sigma))
        return NormalDist(x1.mu - x2, x1.sigma)

    def __mul__(x1, x2):
        return NormalDist(x1.mu * x2, x1.sigma * fabs(x2))

    def __truediv__(x1, x2):
        return NormalDist(x1.mu / x2, x1.sigma / fabs(x2))

    def __pos__(x1):
        return NormalDist(x1.mu, x1.sigma)

    def __neg__(x1):
        return NormalDist(-x1.mu, x1.sigma)

    __radd__ = __add__

    def __rsub__(x1, x2):
        return -(x1 - x2)

    __rmul__ = __mul__

    def __eq__(x1, x2):
        if not isinstance(x2, NormalDist):
            return NotImplemented
        return (x1.mu, x2.sigma) == (x2.mu, x2.sigma)

    def __repr__(self):
        return "%s(mu=%s, sigma=%s)" % (type(self).__name__,
                                        repr(self.mu),
                                        repr(self.sigma))


if __name__ == '__main__':

    # Show math operations computed analytically in comparsion
    # to a monte carlo simulation of the same operations

    from operator import add, sub, mul, truediv
    from itertools import repeat

    g1 = NormalDist(10, 20)
    g2 = NormalDist(-5, 25)

    # Test scaling by a constant
    assert (g1 * 5 / 5).mu == g1.mu
    assert (g1 * 5 / 5).sigma == g1.sigma

    n = 100000
    G1 = g1.samples(n)
    G2 = g2.samples(n)

    for func in (add, sub):
        print(u'\nTest %s with another NormalDist:' % func.__name__)
        print(func(g1, g2))
        print(NormalDist.from_samples(map(func, G1, G2)))

    const = 11
    for func in (add, sub, mul, truediv):
        print(u'\nTest %s with a constant:' % func.__name__)
        print(func(g1, const))
        print(NormalDist.from_samples(map(func, G1, repeat(const, len(G1)))))

    const = 19
    for func in (add, sub, mul):
        print(u'\nTest constant with %s:' % func.__name__)
        print(func(const, g1))
        print(NormalDist.from_samples(map(func, repeat(const, len(G1)), G1)))

    def isclose(a, b, rel_tol=1e-9, abs_tol=0.0):
        return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

    def assert_close(G1, G2):
        assert isclose(G1.mu, G1.mu, rel_tol=0.01), (G1, G2)
        assert isclose(G1.sigma, G2.sigma, rel_tol=0.01), (G1, G2)

    X = NormalDist(-105, 73)
    Y = NormalDist(31, 47)
    s = 32.75
    n = 100000

    S = NormalDist.from_samples([x + s for x in X.samples(n)])
    assert_close(X + s, S)

    S = NormalDist.from_samples([x - s for x in X.samples(n)])
    assert_close(X - s, S)

    S = NormalDist.from_samples([x * s for x in X.samples(n)])
    assert_close(X * s, S)

    S = NormalDist.from_samples([x / s for x in X.samples(n)])
    assert_close(X / s, S)

    S = NormalDist.from_samples([x + y for x, y in zip(X.samples(n),
                                                       Y.samples(n))])
    assert_close(X + Y, S)

    S = NormalDist.from_samples([x - y for x, y in zip(X.samples(n),
                                                       Y.samples(n))])
    assert_close(X - Y, S)
