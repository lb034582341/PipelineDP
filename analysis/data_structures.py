# Copyright 2022 OpenMined.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contains API dataclasses."""

import copy
import dataclasses
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import pipeline_dp
from pipeline_dp import input_validators


@dataclasses.dataclass
class MultiParameterConfiguration:
    """Specifies parameters for multi-parameter Utility Analysis.

    All MultiParameterConfiguration attributes corresponds to attributes in
    pipeline_dp.AggregateParams.

    UtilityAnalysisEngine can perform utility analysis for multiple sets of
    parameters simultaneously. API for this is the following:
    1. Specify blue-print AggregateParams instance.
    2. Set MultiParameterConfiguration attributes (see the example below). Note
    that each attribute is a sequence of parameter values for which the utility
    analysis will be run. All attributes that have non-None values must have
    the same length.
    3. Pass the created objects to UtilityAnalysisEngine.aggregate().

    Example:
        max_partitions_contributed = [1, 2]
        max_contributions_per_partition = [10, 11]

        Then the utility analysis will be performed for
          AggregateParams(max_partitions_contributed=1, max_contributions_per_partition=10)
          AggregateParams(max_partitions_contributed=2, max_contributions_per_partition=11)
    """
    max_partitions_contributed: Sequence[int] = None
    max_contributions_per_partition: Sequence[int] = None
    min_sum_per_partition: Union[Sequence[float],
                                 Sequence[Sequence[float]]] = None
    max_sum_per_partition: Union[Sequence[float],
                                 Sequence[Sequence[float]]] = None
    noise_kind: Sequence[pipeline_dp.NoiseKind] = None
    partition_selection_strategy: Sequence[
        pipeline_dp.PartitionSelectionStrategy] = None

    def __post_init__(self):
        attributes = dataclasses.asdict(self)
        sizes = [len(value) for value in attributes.values() if value]
        if not sizes:
            raise ValueError("MultiParameterConfiguration must have at least 1"
                             " non-empty attribute.")
        if min(sizes) != max(sizes):
            raise ValueError(
                "All set attributes in MultiParameterConfiguration must have "
                "the same length.")
        self._size = sizes[0]
        if (self.min_sum_per_partition is None) != (self.max_sum_per_partition
                                                    is None):
            raise ValueError(
                "MultiParameterConfiguration: min_sum_per_partition and "
                "max_sum_per_partition must be both set or both None.")
        if self.min_sum_per_partition:
            # If elements of min_sum_per_partition and max_sum_per_partition are
            # sequences, all of them should have the same size.
            def all_elements_are_lists(a: list):
                return all([isinstance(b, Sequence) for b in a])

            def common_value_len(a: list) -> Optional[int]:
                sizes = [len(v) for v in a]
                return min(sizes) if min(sizes) == max(sizes) else None

            if all_elements_are_lists(
                    self.min_sum_per_partition) and all_elements_are_lists(
                        self.max_sum_per_partition):
                # multi-column case. Check that each configuration has the
                # same number of elements (i.e., columns)
                size1 = common_value_len(self.min_sum_per_partition)
                size2 = common_value_len(self.max_sum_per_partition)
                if size1 is None or size2 is None or size1 != size2:
                    raise ValueError("If elements of min_sum_per_partition and "
                                     "max_sum_per_partition are sequences, then"
                                     " they must have the same length.")

    @property
    def size(self):
        return self._size

    def get_aggregate_params(
        self, params: pipeline_dp.AggregateParams, index: int
    ) -> Tuple[pipeline_dp.AggregateParams, List[Tuple[float, float]]]:
        """Returns AggregateParams with the index-th parameters."""
        params = copy.copy(params)
        if self.max_partitions_contributed:
            params.max_partitions_contributed = self.max_partitions_contributed[
                index]
        if self.max_contributions_per_partition:
            params.max_contributions_per_partition = self.max_contributions_per_partition[
                index]
        if self.noise_kind:
            params.noise_kind = self.noise_kind[index]
        if self.partition_selection_strategy:
            params.partition_selection_strategy = self.partition_selection_strategy[
                index]
        min_max_sum = []
        if self.min_sum_per_partition:
            min_sum = self.min_sum_per_partition[index]
            max_sum = self.max_sum_per_partition[index]
            if isinstance(min_sum, Sequence):
                min_max_sum = list(zip(min_sum, max_sum))
            else:
                min_max_sum = [[min_sum, max_sum]]
        else:
            min_max_sum.append(
                [params.min_sum_per_partition, params.max_sum_per_partition])
        return params, min_max_sum


@dataclasses.dataclass
class UtilityAnalysisOptions:
    """Options for the utility analysis."""
    epsilon: float
    delta: float
    aggregate_params: pipeline_dp.AggregateParams
    multi_param_configuration: Optional[MultiParameterConfiguration] = None
    partitions_sampling_prob: float = 1
    pre_aggregated_data: bool = False

    def __post_init__(self):
        input_validators.validate_epsilon_delta(self.epsilon, self.delta,
                                                "UtilityAnalysisOptions")
        if self.partitions_sampling_prob <= 0 or self.partitions_sampling_prob > 1:
            raise ValueError(
                f"partitions_sampling_prob must be in the interval"
                f" (0, 1], but {self.partitions_sampling_prob} given.")

    @property
    def n_configurations(self):
        if self.multi_param_configuration is None:
            return 1
        return self.multi_param_configuration.size


def get_aggregate_params(
    options: UtilityAnalysisOptions
) -> Iterable[Tuple[pipeline_dp.AggregateParams, List[Tuple[float, float]]]]:
    """Returns AggregateParams which are specified by UtilityAnalysisOptions."""
    multi_param_configuration = options.multi_param_configuration
    if multi_param_configuration is None:
        agg_params = options.aggregate_params
        yield agg_params, [[
            agg_params.min_sum_per_partition, agg_params.max_sum_per_partition
        ]]
    else:
        for i in range(multi_param_configuration.size):
            yield multi_param_configuration.get_aggregate_params(
                options.aggregate_params, i)


def get_partition_selection_strategy(
    options: UtilityAnalysisOptions
) -> Sequence[pipeline_dp.PartitionSelectionStrategy]:
    """Returns partition selection strategies for different configurations."""
    multi_configuration = options.multi_param_configuration
    n_configurations = 1
    if multi_configuration is not None:
        if multi_configuration.partition_selection_strategy is not None:
            # Different parameter configurations have different partition
            # selection strategies.
            return multi_configuration.partition_selection_strategy
        n_configurations = multi_configuration.size
    # The same partition selection strategy for all configuration.
    return [options.aggregate_params.partition_selection_strategy
           ] * n_configurations
