# This file is part of daf_butler.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (http://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from .utils import slotValuesAreEqual

from .execution import Execution

__all__ = ("Quantum",)


class Quantum(Execution):
    """A discrete unit of work that may depend on one or more datasets and
    produces one or more datasets.

    Most Quanta will be executions of a particular `SuperTask`’s `runQuantum`
    method, but they can also be used to represent discrete units of work
    performed manually by human operators or other software agents.

    Parameters
    ----------
    task : `str` or `SuperTask`
        Fully-qualified name of the SuperTask that executed this Quantum.
    run : `Run`
        The Run this Quantum is a part of.
    """

    __slots__ = ("_task", "_run", "_predictedInputs", "_actualInputs", "_outputs")
    __eq__ = slotValuesAreEqual

    def __init__(self, task, run, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._task = task
        self._run = run
        self._predictedInputs = {}
        self._actualInputs = {}
        self._outputs = {}

    @property
    def task(self):
        """Task associated with this `Quantum`.

        If the `Quantum` is associated with a `SuperTask`, this is the
        `SuperTask` instance that produced and should execute this set of
        inputs and outputs. If not, a human-readable string identifier
        for the operation. Some Registries may permit the value to be
        `None`, but are not required to in general.
        """
        return self._task

    @property
    def run(self):
        """The Run this Quantum is a part of (`Run`).
        """
        return self._run

    @property
    def predictedInputs(self):
        """A `dict` of input datasets that were expected to be used,
        with `DatasetType` names as keys and a list of `DatasetRef` instances
        as values.

        Input `Datasets` that have already been stored may be
        `DatasetRef`\s, and in many contexts may be guaranteed to be.
        Read-only; update via `Quantum.addPredictedInput()`.
        """
        return self._predictedInputs

    @property
    def actualInputs(self):
        """A `dict` of input datasets that were actually used, with the same
        form as `Quantum.predictedInputs`.

        All returned sets must be subsets of those in `predictedInputs`.

        Read-only; update via `Registry.markInputUsed()`.
        """
        return self._actualInputs

    @property
    def outputs(self):
        """A `dict` of output datasets (to be) generated for this quantum,
        with the same form as `predictedInputs`.

        Read-only; update via `addOutput()`.
        """
        return self._outputs

    def addPredictedInput(self, ref):
        """Add an input `DatasetRef` to the `Quantum`.

        This does not automatically update a `Registry`; all `predictedInputs`
        must be present before a `Registry.addQuantum()` is called.

        Parameters
        ----------
        ref : `DatasetRef`
            Reference for a Dataset to add to the Quantum's predicted inputs.
        """
        datasetTypeName = ref.datasetType.name
        if datasetTypeName not in self._actualInputs:
            self._predictedInputs[datasetTypeName] = [ref, ]
        else:
            self._predictedInputs[datasetTypeName].append(ref)

    def _markInputUsed(self, ref):
        """Mark an input as used.

        This does not automatically update a `Registry`.
        For that use `Registry.markInputUsed()` instead.
        """
        datasetTypeName = ref.datasetType.name
        # First validate against predicted
        if datasetTypeName not in self._predictedInputs:
            raise ValueError("Dataset type {} not in predicted inputs".format(datasetTypeName))
        if ref not in self._predictedInputs[datasetTypeName]:
            raise ValueError("Actual input {} was not predicted".format(ref))
        # Now insert as actual
        if datasetTypeName not in self._actualInputs:
            self._actualInputs[datasetTypeName] = [ref, ]
        else:
            self._actualInputs[datasetTypeName].append(ref)

    def addOutput(self, ref):
        """Add an output `DatasetRef` to the `Quantum`.

        This does not automatically update a `Registry`; all `outputs`
        must be present before a `Registry.addQuantum()` is called.

        Parameters
        ----------
        ref : `DatasetRef`
            Reference for a Dataset to add to the Quantum's outputs.
        """
        datasetTypeName = ref.datasetType.name
        self._outputs.setdefault(datasetTypeName, []).append(ref)
