import random
import warnings

from .partitionedsink import PartitionedFileSink
from .partitionedsink import T

import apache_beam as beam
from apache_beam import PTransform
from apache_beam import core
from apache_beam.transforms import window
from apache_beam.io.filesystem import CompressionTypes

from pipe_tools.timestamp import SECONDS_IN_DAY
from pipe_tools.timestamp import datetimeFromTimestamp
from pipe_tools.coders import JSONDictCoder
from pipe_tools.coders import JSONDict
from apache_beam import typehints
from apache_beam.typehints import Tuple, KV


DEFAULT_SHARDS_PER_DAY = 3


@typehints.with_input_types(JSONDict)
@typehints.with_output_types(str)
class WriteToDatePartitionedFiles(PTransform):
    """
    Write the incoming pcoll to files partitioned by date.  The date is taken from the
    TimestampedValue associated with each element.

    """
    def __init__(self,
                 file_path_prefix,
                 file_name_suffix='',
                 append_trailing_newlines=True,
                 shards_per_day=None,
                 shard_name_template=None,
                 coder=JSONDictCoder(),
                 compression_type=CompressionTypes.AUTO,
                 header=None):

        self.shards_per_day = shards_per_day or DEFAULT_SHARDS_PER_DAY

        self._sink = DatePartitionedFileSink(file_path_prefix,
                                             file_name_suffix=file_name_suffix,
                                             append_trailing_newlines=append_trailing_newlines,
                                             shard_name_template=shard_name_template,
                                             coder=coder,
                                             compression_type=compression_type,
                                             header=header)

    def expand(self, pcoll):
        pcoll = (
            pcoll
            | core.WindowInto(window.GlobalWindows())
            | beam.ParDo(DateShardDoFn(shards_per_day=self.shards_per_day))
            | beam.GroupByKey()   # group by day and shard
        )
        with warnings.catch_warnings():
            # suppress a spurious warning generated within beam.io.Write.  This warning is annoying but harmless
            warnings.filterwarnings(action="ignore", message="Using fallback coder for typehint: <type 'NoneType'>")

            return pcoll | beam.io.Write(self._sink).with_output_types(str)




@typehints.with_input_types(T)
@typehints.with_output_types(KV[Tuple[int,int],T])
class DateShardDoFn(beam.DoFn):
    """
    Apply date and shard number
    """

    def __init__(self, shards_per_day=None):
        self.shards_per_day = shards_per_day or DEFAULT_SHARDS_PER_DAY
        self.shard_counter = 0

    def start_bundle(self):
        self.shard_counter = random.randint(0, self.shards_per_day - 1)

    def process(self, element, timestamp=beam.DoFn.TimestampParam):
        # get the timestamp at the start of the day that contains this element
        date = (int(timestamp) / SECONDS_IN_DAY) * SECONDS_IN_DAY
        shard = self.shard_counter

        self.shard_counter += 1
        if self.shard_counter >= self.shards_per_day:
            self.shard_counter -= self.shards_per_day
        assert isinstance(element, JSONDict), 'element must be a JSONDict'
        # get timestamp from TimestampedValue
        yield ((date, shard), element)


class DatePartitionedFileSink(PartitionedFileSink):
    DATE_FORMAT='%Y-%m-%d'
    def _encode_key(self, date_ts):
        """convert a timestamp to a string date representation"""
        return datetimeFromTimestamp(date_ts).strftime(self.DATE_FORMAT)