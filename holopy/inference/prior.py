# Copyright 2011-2016, Vinothan N. Manoharan, Thomas G. Dimiduk,
# Rebecca W. Perry, Jerome Fung, and Ryan McGorty, Anna Wang
#
# This file is part of HoloPy.
#
# HoloPy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# HoloPy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with HoloPy.  If not, see <http://www.gnu.org/licenses/>.

import numpy as np
from numpy import random
from numbers import Number

from holopy.core.metadata import get_extents, get_spacing
from holopy.core.process import center_find
from holopy.core.holopy_object import HoloPyObject
from holopy.fitting.errors import ParameterSpecificationError

EPS = 1e-6

class Prior(HoloPyObject):
    def __add__(self, value):
        if isinstance(value, Fixed):
            value = value.guess
        if isinstance(value, Number):
            return self.__addadd__(value)
        elif isinstance(value, np.ndarray):
            return np.array([self + val for val in value])
        else:
            raise TypeError("Cannot add prior to objects of type {}".format(type(value)))

    def __mul__(self, value):
        if isinstance(value, Fixed):
            value = value.guess
        if isinstance(value, Number):
            if value > 0:
                return self.__multiply__(value)
            elif value < 0:
                return -self.__multiply__(-value)
            else:
                TypeError("Cannot multiply a prior by 0")
        elif isinstance(value, np.ndarray):
            return np.array([self * val for val in value])
        else:
            raise TypeError("Cannot multiply prior by objects of type {}".format(type(value)))

    def __radd__(self, value):
        return self + value

    def __sub__(self, value):
        return self + (-value)

    def __rsub__(self, value):
        return -self + value

    def __rmul__(self, value):
        return self * value

    def __truediv__(self, value):
        return self * (1/value)

    def scale(self, physical):
        return physical / self.scale_factor

    def unscale(self, scaled):
        return scaled * self.scale_factor


class Fixed(Prior):
    def __init__(self, guess, name=None):
        if not np.isscalar(guess):
            raise ParameterSpecificationError(
                    "Guess {} is not a scalar value.".format(guess))
        self.guess = guess
        self.name = name
        self.scale_factor = abs(self.guess)

    def lnprob(self, p):
        if p == self.guess:
            return 0
        else:
            return -np.inf

    def prob(self, p):
        if p == self.guess:
            return 1
        else:
            return 0

    def sample(self, size=None):
        if size is None:
            return self.guess
        return np.array([self.guess] * size)

    def __addadd__(self, value):
        return Fixed(self.guess + value, self.name)

    def __multiply(self, value):
        return Fixed(self.guess * value, self.name)

    def __neg__(self):
        return Fixed(-self.guess, self,name)


class Uniform(Prior):
    def __init__(self, lower_bound, upper_bound, guess=None, name=None):
        if lower_bound > upper_bound:
            raise ParameterSpecificationError(
                    "Lower bound {} is greater than upper bound {}".format(
                    lower_bound, upper_bound))
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.name = name

        if np.isfinite(self.interval):
            self._lnprob = np.log(1/self.interval)
        else:
            self._lnprob = -1/EPS # don't want -inf to add likelihood

        if guess is None:
            self.guess = (upper_bound + lower_bound)/2
        elif guess < lower_bound or guess > upper_bound:
            raise ParameterSpecificationError(
                    "Guess {} is not within bounds {} and {}.".format(
                    guess, lower_bound, upper_bound))
        else:
            self.guess = guess

        if abs(self.guess) > 1e-12:
            self.scale_factor = abs(self.guess)
        elif np.isfinite(self.interval):
            self.scale_factor = self.interval/10.
        else:
            self.scale_factor = 1.

    def lnprob(self, p):
        if p < self.lower_bound or p > self.upper_bound:
            return -np.inf
        # For a uniform prior, the value is the same every time, so we precompute it
        return self._lnprob
        # Turns out scipy.stats is noticably slower than doing it ourselves
        #return stats.uniform.logpdf(p, self.lower_bound, self.upper_bound)

    def prob(self, p):
        if p < self.lower_bound or p > self.upper_bound:
            return 0
        return 1/self.interval

    @property
    def interval(self):
        return(self.upper_bound - self.lower_bound)

    def sample(self, size=None):
        return random.uniform(self.lower_bound, self.upper_bound, size)

    def __addadd__(self, value):
        return Uniform(self.lower_bound+value, self.upper_bound+value, self.name)

    def __multiply__(self, value):
        return Uniform(self.lower_bound*value, self.upper_bound*value, self.name)

    def __neg__(self):
        return Uniform(-self.upper_bound, -self.lower_bound)

class Gaussian(Prior):
    def __init__(self, mu, sd, name=None):
        self.mu = mu
        self.sd = sd
        if sd <= 0:
            raise ParameterSpecificationError(
                    "Specified sd of {} is not greater than 0".format(sd))
        self.sdsq = sd**2
        self.name=name
        self._lnprob_normalization = -np.log(self.sd * np.sqrt(2*np.pi))

        if abs(self.guess) > 1e-12:
            self.scale_factor = abs(self.guess)
        else:  # values near 0
            self.scale_factor = self.sd

    def lnprob(self, p):
        return self._lnprob_normalization - (p-self.mu)**2/(2*self.sdsq)
        # Turns out scipy.stats is noticably slower than doing it ourselves
        #return stats.norm.logpdf(p, self.mu, self.sd)

    def prob(self, p):
        return stats.norm.pdf(p, self.mu, self.sd)

    @property
    def guess(self):
        return self.mu

    def sample(self, size=None):
        return random.normal(self.mu, self.sd, size=size)

    def __add__(self, value):
        if isinstance(value, Gaussian) and not isinstance(value, BoundedGaussian) and not isinstance(self, BoundedGaussian):
            new_sd = np.sqrt(self.sd**2 + value.sd**2)
            if self.name == value.name:
                new_name = self.name
            else:
                new_name = "GaussianSum"
            return Gaussian(self.mu + value.mu, new_sd, new_name)
        else:
            return super().__add__(value)

    def __addadd__(self, value):
        return Gaussian(self.mu+value, self.sd, self.name)

    def __multiply__(self, value):
        return Gaussian(self.mu*value, self.sd*value, self.name)

    def __neg__(self):
        return Gaussian(-self.mu, self.sd, self.name)

class BoundedGaussian(Gaussian):
    # Note: this is not normalized
    def __init__(self, mu, sd, lower_bound=-np.inf, upper_bound=np.inf, name=None):

        if lower_bound > upper_bound:
            raise ParameterSpecificationError("Lower bound {} is greater than upper bound {}".format(lower_bound, upper_bound))
        if mu < lower_bound or mu > upper_bound:
            raise ParameterSpecificationError("Gaussian mean {} is not between bounds {} and {}.".format(mu, lower_bound, upper_bound))

        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        super(BoundedGaussian, self).__init__(mu, sd, name)

    def lnprob(self, p):
        if np.any(p < self.lower_bound) or np.any(p > self.upper_bound):
            return -np.inf
        else:
            return super(BoundedGaussian, self).lnprob(p)

    def sample(self, size=None):
        val = super(BoundedGaussian, self).sample(size)
        out = True
        while np.any(out):
            out = np.where(np.logical_or(val < self.lower_bound, val > self.upper_bound))
            val[out] = super(BoundedGaussian, self).sample(len(out[0]))
        return val

    def __addadd__(self, value):
        return BoundedGaussian(self.mu+value, self.sd, self.lower_bound+value, self.upper_bound+value, self.name)

    def __multiply__(self, value):
        return BoundedGaussian(self.mu*value, self.sd*value, self.lower_bound*value, self.upper_bount*value, self.name)

    def __neg__(self):
        return BoundedGaussian(-self.mu, self.sd, -self.upper_bound, -self.lower_bound, self.name)


class ComplexPrior(Prior):
    """
    A complex free parameter

    ComplexPrior has a real and imaginary part which can (potentially)
    vary separately.

    Parameters
    ----------
    real, imag : float or :class:`Prior`
        The real and imaginary parts of this parameter.  Assign floats to fix
        that portion or parameters to allow it to vary.  The parameters must be
        purely real.  You should omit names for the parameters;
        ComplexPrior will name them
    name : string
        Short descriptive name of the ComplexPrior.  Do not provide this if
        using a ParameterizedScatterer, a name will be assigned based its
        position within the scatterer.
    """
    def __init__(self, real, imag, name = None):
        '''
        real and imag may be scalars or Priors. If Priors, they must be
        pure real.
        '''
        if not isinstance(real, Prior):
            real = Fixed(real)
        self.real = real
        if not isinstance(imag, Prior):
            imag = Fixed(imag)
        self.imag = imag
        self.name = name

    @property
    def guess(self):
        return self.real.guess + 1.0j * self.imag.guess

    def lnprob(self, p):
        realprob = real.lnprob(np.real(p))
        imagprob = imag.lnprob(np.imag(p))
        return realprob + imagprob

    def prob(self, p):
        realprob = real.prob(np.real(p))
        imagprob = imag.prob(np.imag(p))
        return realprob * imagprob

    def sample(self, size=None):
        return self.real.sample(size) + 1.0j * self.imag.sample(size)

    def __addadd__(self, value):
        real = self.real + np.real(value)
        imag = self.imag + np.imag(value)
        return ComplexPrior(real, imag, self.name)

    def __multiply__(self, value):
        # This doesn't work for complex "value"
        return ComplexPrior(self.real * value, self.imag * value, self.name)

    def __neg__(self):
        return ComplexPrior(-self.real, -self.imag, self.name)


def updated(prior, v, extra_uncertainty=0):
    """
    Update a prior from a posterior

    Parameters
    ----------
    v : UncertainValue
        The new value, usually from an mcmc result
    extra_uncertainty : float
        provide a floor for uncertainty (sd) of the new parameter
    """
    sd = max(v.plus, v.minus, extra_uncertainty)
    if hasattr(prior, 'lower_bound'):
        return BoundedGaussian(v.value, sd,
                               getattr(prior, 'lower_bound', -np.inf),
                               getattr(prior, 'upper_bound', np.inf),
                               name=prior.name)
    else:
        return Gaussian(v.value, sd, prior.name)

def make_center_priors(im, z_range_extents=5, xy_uncertainty_pixels=1, z_range_units=None):
    """
    Make sensible default priors for the center of a sphere in a hologram

    Parameters
    ----------
    im : xarray
         The image you wish to make priors for
    z_range_extents : float (optional)
         What range to extend a uniform prior for z over, measured in multiples
         of the total extent of the image. The default is 5 times the extent of
         the image, a large range, but since tempering is quite good at refining
         this, it is safer to just choose a large range to be sure to include
         the correct value.
    xy_uncertainty_pixels: float (optional)
         The number of pixels of uncertainty to assume for the centerfinder.
         The default is 1 pixel, and this is probably correct for most images.
    z_range_units : float
         Specify the range of the z prior in your data units. If this is provided,
         z_range_extents is ignored.
    """
    if z_range_units is not None:
        z_range = z_range_units
    else:
        extents = get_extents(im)
        extent = max(extents['x'], extents['y'])
        z_range = 0, extent * z_range_extents

    spacing = get_spacing(im)
    center = center_find(im) * spacing + [im.x[0], im.y[0]]

    xy_sd = xy_uncertainty_pixels * spacing
    return [Gaussian(c, s) for c, s in zip(center, xy_sd)] + [Uniform(*z_range)]
