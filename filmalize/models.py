"""Custom objects for filmalize."""

import os
import datetime
import tempfile
import subprocess
import json
from pathlib import PurePath

import chardet
import bitmath

from filmalize.errors import ProbeError

DEFAULT_BITRATE = 384
DEFAULT_CRF = 18


class ContainerLabel(object):
    """Labels for Container objects"""

    def __init__(self, title=None, size=None, bitrate=None,
                 container_format=None):
        """Populate Container Label object instance variables.

        Note:
            The information stored here is simply for display and will not
            affect the output file.

            All arguments are optional.

        Args:
            title (str, optional): Container title label.
            size (float, optional): Container size label in MiBs.
            bitrate (float, optional): Container bitrate label in Mib/s.
            container_format (str, optional): Container format label.
                Regardless of the presence of this label, the container must be
                a format that ffmpeg can process.

        """
        self.title = title if title else ''
        self.size = size if size else ''
        self.bitrate = bitrate if bitrate else ''
        self.container_format = container_format if container_format else ''


class Container(object):
    """Multimedia container file object."""

    def __init__(self, file_name, duration, streams, subtitle_files=None,
                 selected=None, output_name=None, labels=None):
        """Populate container object properties and instance variables.

        Args:
            file_name (str): The multimedia container file to represent.
            duration (float): The duration of the streams in the container in
                seconds.
            streams (list): The Stream objects representing the mutimedia
                streams in this container.
            subtitle_files (list, optional): SubtitleFile objects representing
                subtitle files to add to the output file.
            selected (list, optional): Integer stream indexes of the streams to
                include in the output file. If not specified, the first audio
                and video stream will be selected.
            output_name (str, optional): Output filename. If not specified, the
                output filename will be set to the input file, but with '.mp4'
                replacing the extension.
            labels (ContainerLabel, optional): Informational metadata about the
                input file.

        """

        self.file_name = file_name
        self.duration = duration
        self.streams = streams
        self.subtitle_files = subtitle_files if subtitle_files else []
        self.output_name = output_name if output_name else self.default_name()
        self.selected = selected if selected else self.default_streams()
        self.labels = labels if labels else ContainerLabel()

        self.microseconds = int(duration * 1000000)
        self.length = datetime.timedelta(seconds=round(duration, 0))
        self.temp_file = tempfile.NamedTemporaryFile()
        self.progress = 0
        self.process = None

    @classmethod
    def from_file(cls, file_name):
        """Build a Container instance from a given file.

        Attempt to probe the file with ffprobe. If the probe is succesful,
        finish instatiation using the results of the probe, building Stream
        instances as necessary.

        Args:
            file_name (str): The file (a multimedia container) to represent.

        Returns:
            Container: Instance representing the given file.

        Raises:
            ProbeError: If ffprobe is unable to successfully probe the file.

        """

        probe_response = subprocess.run(
            ['/usr/bin/ffprobe', '-v', 'error', '-show_format',
             '-show_streams', '-of', 'json', file_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if probe_response.returncode:
            raise ProbeError(file_name, probe_response.stderr.decode('utf-8')
                             .strip(os.linesep))
        else:
            probe_info = json.loads(probe_response.stdout)
            labels = ContainerLabel()
            duration = float(probe_info['format']['duration'])
            streams = [Stream.from_dict(stream)
                       for stream in probe_info['streams']]

            if ('tags' in probe_info['format']
                    and 'title' in probe_info['format']['tags']):
                labels.title = probe_info['format']['tags']['title']
            if 'size' in probe_info['format']:
                file_bytes = int(probe_info['format']['size'])
                labels.size = round(bitmath.MiB(bytes=file_bytes).value, 2)
            if 'bit_rate' in probe_info['format']:
                bits = int(probe_info['format']['bit_rate'])
                labels.bitrate = round(bitmath.Mib(bits=bits).value, 2)
            if 'format_name' in probe_info['format']:
                labels.container_format = probe_info['format']['format_name']

        return cls(file_name, duration, streams, labels=labels)

    @property
    def streams_dict(self):
        """dict: The streams keyed by their indexes."""
        return {stream.index: stream for stream in self.streams}

    def acceptable_streams(self, index_list):
        """Determine if all of the indexes in a list match a Stream in
             self.streams.

        Args:
            index_list (list of int): Indexes that may correspond to Streams.

        Returns:
            bool: True if all of the indexes are valid.

        Raises:
            StreamSelectionError: If list contains an index that does not
                correspond to any Stream in self.streams.

        """

        streams = self.streams_dict
        for index in index_list:
            if index not in streams.keys():
                raise ValueError('This contaner does not contain a stream '
                                 'with index {}'.format(index))
            if streams[index].type not in ['audio', 'video', 'subtitle']:
                raise ValueError('filmalize cannot output streams of type {}'
                                 .format(streams[index].type))
        return True

    def default_streams(self):
        """Return a list of the indexes of the first video and audio stream."""

        streams = []
        audio, video = None, None
        for stream in self.streams:
            if not audio and stream.type == 'audio':
                audio = True
                streams.append(stream.index)
            elif not video and stream.type == 'video':
                video = True
                streams.append(stream.index)

        return streams

    def default_name(self):
        """Return a string; self.file_name with a '.mp4' ending."""

        return PurePath(self.file_name).stem + '.mp4'

    def add_subtitle_file(self, file_name, encoding):
        """Add an external subtitle file. Allow the user to set a custom
        encoding.

        Args:
            file_name (str): The name of the subtitle file.
            encoding (str): The encoding of the subtitle file.

        """

        index = len(self.subtitle_files + 1)
        self.subtitle_files[index] = SubtitleFile(file_name, encoding)

    def convert(self):
        """Start the conversion of this container in a subprocess."""

        self.process = subprocess.Popen(
            self.build_command(),
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

    def build_command(self):
        """Build the ffmpeg command to process this container.

        Generate appropriate ffmpeg options to process the selected streams.

        Returns:
            list: The ffmpeg command and options to execute.

        """

        command = ['/usr/bin/ffmpeg', '-nostdin', '-progress',
                   self.temp_file.name, '-v', 'error', '-y', '-i',
                   self.file_name]
        for subtitle in self.subtitle_files:
            command.extend(['-sub_charenc', subtitle.encoding, '-i',
                            subtitle.file_name])
        for stream in self.selected:
            command.extend(['-map', '0:{}'.format(stream)])
        for index, _ in enumerate(self.subtitle_files):
            command.extend(['-map', '{}:0'.format(index + 1)])
        stream_number = {'video': 0, 'audio': 0, 'subtitle': 0}
        output_streams = [s for s in self.streams if s.index in self.selected]
        for stream in output_streams:
            command.extend(stream.build_options(stream_number[stream.type]))
            stream_number[stream.type] += 1
        for subtitle in self.subtitle_files:
            command.extend(['-c:s:{}'.format(stream_number['subtitle'])])
            command.extend(subtitle.options)
            stream_number['subtitle'] += 1
        command.extend([os.path.join(os.path.dirname(self.file_name),
                                     self.output_name)])

        return command


class StreamLabel(object):
    """Labels for Stream objects"""

    def __init__(self, title=None, bitrate=None, resolution=None,
                 language=None, channels=None, default=None):
        """Populate StreamLabel object instance variables.

        Note:
            The information stored here is simply for display and (with one
            exception) will not affect the output file.

            For audio streams, if this stream cannot be copied and must be
            transcoded, and if there is a value stored in self.bitrate, that
            value will be chosen by default as the output stream target
            bitrate.

            All Arguments are optional.

        Args:
            title (str): Stream title.
            bitrate (float): Stream bitrate in Mib/s for video streams or Kib/s
                for audio streams.
            resolution (str): Stream resolution.
            language (str): Language name or abbreviation.
            channels (str): Audio channel information (stereo, 5.1, etc.).
            default (bool): True if this stream is the default stream of its
                type, else False.

        """

        self.title = title if title else ''
        self.bitrate = bitrate if bitrate else ''
        self.resolution = resolution if resolution else ''
        self.language = language if language else ''
        self.channels = channels if channels else ''
        self._default = 'default' if default else ''

    @property
    def default(self):
        """str: 'default' if this stream is the default stream of its type,
            else ''.

        Args:
            is_default (bool): True if this stream is the default stream of its
                type, else False.

        """
        return self._default

    @default.setter
    def default(self, is_default):
        self._default = 'default' if is_default else ''


class Stream(object):
    """Multimedia stream object."""

    def __init__(self, index, stream_type, codec, custom_crf=None,
                 custom_bitrate=None, labels=None):
        """Populate Stream object instance variables.

        Args:
            index (int): The stream index.
            stream_type (str): The multimedia type of the stream. Streams will
                be included only if they are of type 'audio', 'video', or
                'subtitle'.
            codec (str): The codec with which the stream is encoded.
            custom_crf (int, optional): Video stream Constant Rate Factor. If
                specified, this stream will be transcoded using this crf even
                if the input stream is suitable for copying to the output file.
            custom_bitrate (float): Audio stream ouput bitrate in Kib/s. If
                specified, this audio stream will be transcoded using this as
                the target bitrate even if the input stream is suitable for
                copying and even if labels.bitrate is set (see StreamLabel).
            labels (StreamLabel, optional): Informational metadata about the
                input stream.

        """

        self.index = index
        self.type = stream_type
        self.codec = codec
        self.custom_crf = custom_crf
        self.custom_bitrate = custom_bitrate
        self.labels = labels if labels else StreamLabel()

        self.option_summary = None

    @classmethod
    def from_dict(cls, stream_info):
        """Build a Stream instance from a dictionary.

            Args:
                stream_info (dict): Stream information in dictionary format
                    structured in the manner of ffprobe json output.

            Returns:
                Stream: Instance populated with data from the given dict.

        """

        index = stream_info['index']
        stream_type = stream_info['codec_type']
        codec = stream_info['codec_name']

        labels = StreamLabel()
        if 'tags' in stream_info and 'language' in stream_info['tags']:
            labels.language = stream_info['tags']['language']
        if ('disposition' in stream_info
                and 'default' in stream_info['disposition']):
            labels.default = bool(stream_info['disposition']['default'])
        if 'tags' in stream_info and 'title' in stream_info['tags']:
            labels.title = stream_info['tags']['title']

        if stream_type == 'video':
            if 'height' in stream_info and 'width' in stream_info:
                width = str(stream_info['width'])
                height = str(stream_info['height'])
                labels.resolution = width + 'x' + height
            elif ('coded_height' in stream_info
                  and 'coded_width' in stream_info):
                width = str(stream_info['coded_width'])
                height = str(stream_info['coded_height'])
                labels.resolution = width + 'x' + height
            if 'bit_rate' in stream_info:
                bits = int(stream_info['bit_rate'])
                labels.bitrate = round(bitmath.Mib(bits=bits).value, 2)
            if 'field_order' in stream_info:
                labels.bitrate = stream_info['field_order']
        elif stream_type == 'audio':
            if 'channel_layout' in stream_info:
                labels.channels = stream_info['channel_layout']
            if 'bit_rate' in stream_info:
                bits = int(stream_info['bit_rate'])
                labels.bitrate = round(bitmath.Kib(bits=bits).value)

        return cls(index, stream_type, codec, labels=labels)

    def build_options(self, number=0):
        """Generate ffmpeg codec/bitrate options for this Stream.

        The options generated will use custom values for video CRF or audio
        bitrate, if specified, or the default values. The option_summary is
        updated to reflect the selected options.

        Args:
            number (int, optional): The number of Streams of this type that
            have been added to the command.

        Returns:
            list: The ffmpeg options for this Stream.

        """

        options = []
        if self.type == 'video':
            options.extend(['-c:v:{}'.format(number)])
            if self.custom_crf or self.codec != 'h264':
                crf = (self.custom_crf if self.custom_crf
                       else DEFAULT_CRF)
                options.extend(['libx264', '-preset', 'slow', '-crf', str(crf),
                                '-pix_fmt', 'yuv420p'])
                self.option_summary = ('transcode -> h264, crf={}'.format(crf))
            else:
                options.extend(['copy'])
                self.option_summary = 'copy'
        elif self.type == 'audio':
            options.extend(['-c:a:{}'.format(number)])
            if self.custom_bitrate or self.codec != 'aac':
                bitrate = (self.custom_bitrate if self.custom_bitrate
                           else self.labels.bitrate if self.labels.bitrate
                           else DEFAULT_BITRATE)
                options.extend(['aac', '-b:a:{}'.format(number),
                                '{}k'.format(bitrate)])
                self.option_summary = ('transcode -> aac, '
                                       'bitrate={}Kib/s').format(bitrate)
            else:
                options.extend(['copy'])
                self.option_summary = 'copy'
        elif self.type == 'subtitle':
            options.extend(['-c:s:{}'.format(number), 'mov_text'])
            self.option_summary = 'transcode -> mov_text'

        return options


class SubtitleFile(object):
    """Subtitle file object."""

    def __init__(self, file_name, encoding=None):
        """Populate SubtitleFile object instance variables.

        Args:
            file_name (str): The subtitle file to represent.
            encoding (str, optional): The file encoding of the subtitle file.

        """
        self.file_name = file_name
        self.encoding = encoding if encoding else self.guess_encoding()
        self.options = ['mov_text']
        self.option_summary = 'transcode -> mov_text'

    def guess_encoding(self):
        """Guess the encoding of the subtitle file.

        Returns:
            str: The best guess for the subtitle file encoding.

        """
        with open(self.file_name, mode='rb') as _file:
            line = _file.readline()
        detected = chardet.detect(line)
        return detected['encoding']
