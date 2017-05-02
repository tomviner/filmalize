"""Core classes for filmalize.

This module contains the classes that do most of the heavy lifting. It should
stand alone, and allow for other interfaces to be built using it. The main
class is the :obj:`Container`, which may be created manually, or with the
:obj:`classmethod` :obj:`Container.from_file`.

"""

import os
import datetime
import tempfile
import subprocess
import json
from pathlib import PurePath

import chardet
import bitmath

import filmalize.defaults as defaults
from filmalize.errors import ProbeError, ProgressFinishedError, NoProgressError


class ContainerLabel(object):
    """Labels for :obj:`Container` objects

    Note:
        The information stored here is simply for display and will not affect
        the output file.

    Args:
        title (:obj:`str`, optional): Container title.
        size (:obj:`float`, optional): Container file size in MiBs.
        bitrate (:obj:`float`, optional): Container overall bitrate in Mib/s.
        container_format (:obj:`str`, optional): Container file format.

    Attributes:
        title (:obj:`str`): Container title.
        size (:obj:`float`): Container file size in MiBs.
        bitrate (:obj:`float`): Container overall bitrate in Mib/s.
        container_format (:obj:`str`): Container file format.

    """

    def __init__(self, title=None, size=None, bitrate=None,
                 container_format=None):

        self.title = title if title else ''
        self.size = size if size else ''
        self.bitrate = bitrate if bitrate else ''
        self.container_format = container_format if container_format else ''


class Container(object):
    """Multimedia container file object.

    Args:
        file_name (:obj:`str`): The name of the input file.
        duration (:obj:`float`): The duration of the streams in the container
            in seconds.
        streams (:obj:`list` of :obj:`Stream`): The mutimedia streams in this
            :obj:`Container`.
        subtitle_files (:obj:`list` of :obj:`SubtitleFile`, optional): Subtitle
            files to add to the output file.
        selected (:obj:`list` of :obj:`int`, optional): Indexes of the
            :obj:`Stream` instances to include in the output file. If not
            specified, the first audio and video stream will be selected.
        output_name (:obj:`str`, optional): Output filename. If not specified,
            the output filename will be set to be the same as the input file,
            but with the extension replaced with the proper one for the
            output format.
        labels (:obj:`ContainerLabel`, optional): Informational metadata about
            the input file.

    Attributes:
        file_name (:obj:`str`): The name of the input file.
        duration (:obj:`float`): The duration of the streams in the container
            in seconds.
        streams (:obj:`list` of :obj:`Stream`): The mutimedia streams in this
            :obj:`Container`.
        subtitle_files (:obj:`list` of :obj:`SubtitleFile`): Subtitle files to
            add to the output file.
        selected (:obj:`list` of :obj:`int`): Indexes of the :obj:`Stream`
            instances to include in the output file.
        output_name (:obj:`str`): Output filename.
        labels (:obj:`ContainerLabel`): Informational metadata about the input
            file.
        microseconds (:obj:`int`): The duration of the file expressed in
            microseconds.
        length (:obj:`datetime.timedelta`): The duration of the file as a
            timedelta.
        temp_file (:obj:`tempfile.NamedTemporaryFile`): The temporary file for
            ffmpeg to write status information to.
        process (:obj:`subprocess.Popen`): The subprocess in which ffmpeg
            processes the file.

    """

    def __init__(self, file_name, duration, streams, subtitle_files=None,
                 selected=None, output_name=None, labels=None):

        self.file_name = file_name
        self.duration = duration
        self.streams = streams
        self.subtitle_files = subtitle_files if subtitle_files else []
        self.output_name = output_name if output_name else self.default_name
        self.selected = selected if selected else self.default_streams
        self.labels = labels if labels else ContainerLabel()

        self.microseconds = int(duration * 1000000)
        self.length = datetime.timedelta(seconds=round(duration, 0))
        self.temp_file = tempfile.NamedTemporaryFile()
        self.process = None

    @classmethod
    def from_file(cls, file_name):
        """Build a :obj:`Container` from a given multimedia file.

        Attempt to probe the file with ffprobe. If the probe is succesful,
        finish instatiation using the results of the probe, building
        :obj:`Stream` instances as necessary.

        Args:
            file_name (:obj:`str`): The file (a multimedia container) to
                represent.

        Returns:
            :obj:`Container`: Instance representing the given file.

        Raises:
            :obj:`ProbeError`: If ffprobe is unable to successfully probe the
                file.

        """

        probe_response = subprocess.run(
            [defaults.FFPROBE, '-v', 'error', '-show_format',
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
    def default_name(self):
        """:obj:`str`: The input filename reformatted with the selected output
        file extension."""

        return PurePath(self.file_name).stem + defaults.ENDING

    @property
    def default_streams(self):
        """:obj:`list` of :obj:`int`: The indexes of the first video and audio
        :obj:`Stream`."""

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

    @property
    def streams_dict(self):
        """:obj:`dict` of {:obj:`int`: :obj:`Stream`}: The :obj:`Stream`
        instances in :obj:`Container.streams` keyed by their indexes."""
        return {stream.index: stream for stream in self.streams}

    @property
    def progress(self):
        """:obj:`int`: The number of microseconds that ffmpeg has processed.

        Raises:
            :obj:`ProgressFinishedError`: If the subprocess is not running
                (either finished or errored out).
            :obj:`NoProgressError`: If unable to read the progress from the
                temp_file.

        """

        if self.process.poll() is not None:
            raise ProgressFinishedError
        else:
            with open(self.temp_file.name, 'r') as status:
                line_list = status.readlines()
            microsec = 0
            for line in reversed(line_list):
                if line.split('=')[0] == 'out_time_ms':
                    try:
                        microsec = int(line.split('=')[1])
                        break
                    except (ValueError, TypeError):
                        raise NoProgressError

            return microsec

    def acceptable_streams(self, index_list):
        """Determine if all of the indexes in a list match a :obj:`Stream` in
        :obj:`self.streams`.

        Note:
            At this time filmalize can only output audio, video, and subtitle
            streams.

        Args:
            index_list (:obj:`list` of :obj:`int`): Indexes that may correspond
                to :obj:`Stream` instances.

        Returns:
            :obj:`bool`: True if all of the indexes are valid.

        Raises:
            :obj:`StreamSelectionError`: If list contains an index that does
                not correspond to any :obj:`Stream` in :obj:`Container.streams`
                or if :obj:`Stream.type` is unsupported.

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

    def add_subtitle_file(self, file_name, encoding=None):
        """Add an external subtitle file. Optionally set a custom file
        encoding.

        Args:
            file_name (:obj:`str`): The name of the subtitle file.
            encoding (:obj:`str`, optional): The encoding of the subtitle file.

        """

        self.subtitle_files.append(SubtitleFile(file_name, encoding))

    def convert(self):
        """Start the conversion of this container in a subprocess."""

        self.process = subprocess.Popen(
            self.build_command(),
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

    def build_command(self):
        """Build the ffmpeg command to process this container.

        Generate appropriate ffmpeg options to process the streams selected in
        :obj:`self.selected`.

        Returns:
            :obj:`list` of :obj:`str`: The ffmpeg command and options to
                execute.

        """

        command = [defaults.FFMPEG, '-nostdin', '-progress',
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
    """Labels for :obj:`Stream` objects.

    Note:
        The information stored here is simply for display and (with one
        exception) will not affect the output file.

        For audio streams, if this stream cannot be copied and must be
        transcoded, and if there is a value stored in self.bitrate, that
        value will be chosen by default as the output stream target
        bitrate.

    Args:
        title (:obj:`str`): Stream title.
        bitrate (:obj:`float`): Stream bitrate in Mib/s for video streams or
            Kib/s for audio streams.
        resolution (:obj:`str`): Stream resolution.
        language (:obj:`str`): Language name or abbreviation.
        channels (:obj:`str`): Audio channel information (stereo, 5.1, etc.).
        default (:obj:`bool`): True if this stream is the default stream of its
            type, else False.

    Attributes:
        title (:obj:`str`): Stream title.
        bitrate (:obj:`float`): Stream bitrate in Mib/s for video streams or
            Kib/s for audio streams.
        resolution (:obj:`str`): Stream resolution.
        language (:obj:`str`): Language name or abbreviation.
        channels (:obj:`str`): Audio channel information (stereo, 5.1, etc.).

    """

    def __init__(self, title=None, bitrate=None, resolution=None,
                 language=None, channels=None, default=None):

        self.title = title if title else ''
        self.bitrate = bitrate if bitrate else ''
        self.resolution = resolution if resolution else ''
        self.language = language if language else ''
        self.channels = channels if channels else ''
        self._default = 'default' if default else ''

    @property
    def default(self):
        """:obj:`str`: 'default' if this stream is the default stream of its
        type, else ''.

        Args:
            is_default (bool): True if this stream is the default stream of its
                type, else False.

        """
        return self._default

    @default.setter
    def default(self, is_default):
        self._default = 'default' if is_default else ''


class Stream(object):
    """Multimedia stream object.

    Note:
        At this time, :obj:`Stream` instances will only be included in the
        output file if they have type of 'audio', 'video', or 'subtitle'.

    Args:
        index (:obj:`int`): The stream index.
        stream_type (:obj:`str`): The multimedia type of the stream as reported
            by ffprobe.
        codec (:obj:`str`): The codec with which the stream is encoded as
            as reported by ffprobe.
        custom_crf (:obj:`int`, optional): Video stream Constant Rate Factor.
            If specified, this stream will be transcoded using this crf even
            if the input stream is suitable for copying to the output file.
        custom_bitrate (:obj:`float`, optional): Audio stream ouput bitrate in
            Kib/s. If specified, this audio stream will be transcoded using
            this as the target bitrate even if the input stream is suitable for
            copying and even if there is a bitrate set in the
            :obj:`StreamLabel`.
        labels (:obj:`StreamLabel`, optional): Informational metadata about the
            input stream.

    Attributes:
        index (:obj:`int`): The stream index.
        stream_type (:obj:`str`): The multimedia type of the stream as reported
            by ffprobe.
        codec (:obj:`str`): The codec with which the stream is encoded as
            as reported by ffprobe.
        custom_crf (:obj:`int`): Video stream Constant Rate Factor.
            If set, this stream will be transcoded using this crf even
            if the input stream is suitable for copying to the output file.
        custom_bitrate (:obj:`float`): Audio stream ouput bitrate in Kib/s. If
            set, this audio stream will be transcoded using this as
            the target bitrate even if the input stream is suitable for
            copying and even if there is a bitrate set in the
            :obj:`StreamLabel`.
        labels (:obj:`StreamLabel`): Informational metadata about the
            input stream.

    """

    def __init__(self, index, stream_type, codec, custom_crf=None,
                 custom_bitrate=None, labels=None):

        self.index = index
        self.type = stream_type
        self.codec = codec
        self.custom_crf = custom_crf
        self.custom_bitrate = custom_bitrate
        self.labels = labels if labels else StreamLabel()

        self.option_summary = None

    @classmethod
    def from_dict(cls, stream_info):
        """Build a :obj:`Stream` instance from a dictionary.

            Args:
                stream_info (:obj:`dict`): Stream information in dictionary
                    format structured in the manner of ffprobe json output.

            Returns:
                :obj:`Stream`: Instance populated with data from the given
                dictionary.

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
        """Generate ffmpeg codec/bitrate options for this :obj:`Stream`.

        The options generated will use custom values for video CRF or audio
        bitrate, if specified, or the default values. The option_summary is
        updated to reflect the selected options.

        Args:
            number (:obj:`int`, optional): The number of Streams of this type
                that have been added to the command.

        Returns:
            :obj:`list` of :obj:`str`: The ffmpeg options for this Stream.

        """

        options = []
        if self.type == 'video':
            options.extend(['-c:v:{}'.format(number)])
            if self.custom_crf or self.codec != defaults.C_VIDEO:
                crf = (self.custom_crf if self.custom_crf
                       else defaults.CRF)
                options.extend(['libx264', '-preset', 'slow', '-crf', str(crf),
                                '-pix_fmt', 'yuv420p'])
                self.option_summary = ('transcode -> {}, crf={}'
                                       .format(defaults.C_VIDEO, crf))
            else:
                options.extend(['copy'])
                self.option_summary = 'copy'
        elif self.type == 'audio':
            options.extend(['-c:a:{}'.format(number)])
            if self.custom_bitrate or self.codec != defaults.C_AUDIO:
                bitrate = (self.custom_bitrate if self.custom_bitrate
                           else self.labels.bitrate if self.labels.bitrate
                           else defaults.BITRATE)
                options.extend([defaults.C_AUDIO, '-b:a:{}'.format(number),
                                '{}k'.format(bitrate)])
                self.option_summary = ('transcode -> {}, bitrate={}Kib/s'
                                       .format(defaults.C_AUDIO, bitrate))
            else:
                options.extend(['copy'])
                self.option_summary = 'copy'
        elif self.type == 'subtitle':
            options.extend(['-c:s:{}'.format(number), defaults.C_SUBS])
            self.option_summary = 'transcode -> {}'.format(defaults.C_SUBS)

        return options


class SubtitleFile(object):
    """Subtitle file object.

    Args:
        file_name (:obj:`str`): The subtitle file to represent.
        encoding (:obj:`str`, optional): The file encoding of the subtitle
            file.

    Attributes:
        file_name (:obj:`str`): The subtitle file represented.
        encoding (:obj:`str`): The file encoding of the subtitle file.


    """

    def __init__(self, file_name, encoding=None):

        self.file_name = file_name
        self.encoding = encoding if encoding else self.guess_encoding()
        self.options = [defaults.C_SUBS]
        self.option_summary = 'transcode -> {}'.format(defaults.C_SUBS)

    def guess_encoding(self):
        """Guess the encoding of the subtitle file.

        Open the given file, read a line, and pass that line to
        :obj:`chardet.detect` to produce a guess at the file's encoding.

        Returns:
            str: The best guess for the subtitle file encoding.

        """
        with open(self.file_name, mode='rb') as _file:
            line = _file.readline()
        detected = chardet.detect(line)
        return detected['encoding']
