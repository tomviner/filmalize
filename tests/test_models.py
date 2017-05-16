"""Unit and Integration tests for filmalize.models"""

import datetime
import json
import os
import subprocess
from collections import namedtuple
from itertools import permutations

import pytest

import filmalize.defaults as defaults
from filmalize.errors import ProgressFinishedError
from filmalize.models import (Container, ContainerLabel, Stream, StreamLabel,
                              SubtitleFile)

with open('example.json') as example_file:
    EXAMPLE = json.load(example_file)

FAKE_CODEC = '_not_a_thing_'


@pytest.fixture
def example_sub_file():
    """Return a SubtitleFile instance built from the example.srt"""
    return SubtitleFile('example.srt', 'ascii')


@pytest.fixture
def example_audio_streamlabel():
    """Return an example StreamLabel which should match the default audio
    stream from example.json."""
    return StreamLabel('Example Audio Stream', 250, '', 'eng', 'stereo', True)


@pytest.fixture
def other_audio_streamlabel():
    """Return an example StreamLabel which should match the non-default audio
    stream from example.json."""
    return StreamLabel('Example Audio Stream', 500, '', 'spa', '5.1', False)


@pytest.fixture
def example_video_streamlabel():
    """Return an example StreamLabel which should match the video stream from
    example.json."""
    return StreamLabel('Example Video Stream', 11.44, '214x160', 'eng', '',
                       True)


@pytest.fixture
def example_sub_streamlabel():
    """Return an example StreamLabel which should match the subtitle stream
    from example.json."""
    return StreamLabel('Example Subtitle Stream', '', '', 'spa', '', False)


@pytest.fixture
def example_audio_stream():
    """Return an example Stream which should match the default audio stream
    from example.json."""
    return Stream(1, 'audio', 'vorbis', '', '', example_audio_streamlabel())


@pytest.fixture
def other_audio_stream():
    """Return an example Stream that should match the non-default audio stream
    from example.json."""
    return Stream(2, 'audio', 'opus', '', '', other_audio_streamlabel())


@pytest.fixture
def example_video_stream():
    """Return an example Stream which should match the video stream from
    example.json."""
    return Stream(0, 'video', 'vp8', '', '', example_video_streamlabel())


@pytest.fixture
def example_sub_stream():
    """Return an example Stream which should match the subtitle stream from
    example.json."""
    return Stream(3, 'subtitle', 'subrip', '', '', example_sub_streamlabel())


@pytest.fixture
def example_container_label():
    """Return an example ContainerLabel that should match one built from
    example.json."""
    return ContainerLabel('Example Container', 4.94, 0.21, 'Matroska / WebM',
                          datetime.timedelta(0, 187))


@pytest.fixture
def example_container():
    """Return an example Container which should match one built from
    example.json."""
    return Container(
        file_name='./examplefile.ogv',
        duration=186.727,
        streams=[example_video_stream(), example_audio_stream(),
                 other_audio_stream(), example_sub_stream()],
        subtitle_files=None,
        selected=[0, 1],
        output_name='examplefile.mp4',
        labels=example_container_label()
    )


@pytest.fixture
def finished_example_container():
    """Return the example container with a mock finished processor object."""
    class Proc:
        """Mock stopped processor."""
        def poll(self):
            """Mock poll method."""
            return True
    built = example_container()
    built.process = Proc()
    return built


@pytest.fixture
def running_example_container():
    """Return the example container with a mock running processor object."""
    class Proc:
        """Mock running processor."""
        def poll(self):
            """Mock poll method."""
            return None
    built = example_container()
    built.process = Proc()
    return built


class TestSubtitleFile:
    """Test the SubtitleFile class."""

    def test_non_file(self):
        """Ensure instantiation with a nonexistant file fails."""
        with pytest.raises(FileNotFoundError):
            SubtitleFile('not_a_file')

    def test_directory(self):
        """Ensure instantiation with a directory fails."""
        with pytest.raises(IsADirectoryError):
            SubtitleFile(os.getcwd())

    def test_example_defaults(self, example_sub_file):
        """Ensure example file is properly represented."""
        assert example_sub_file.file_name == 'example.srt'
        assert example_sub_file.encoding == 'ascii'
        assert example_sub_file.options == [defaults.C_SUBS]
        assert example_sub_file.option_summary == ('transcode -> {}'.
                                                  format(defaults.C_SUBS))
        assert example_sub_file.guess_encoding() == 'ascii'

    def test_example_custom(self):
        """Ensure example file with custom encoding is properly represented."""
        example = SubtitleFile('example.srt', 'UTF-8')
        assert example.encoding == 'UTF-8'
        assert example.guess_encoding() == 'ascii'

    def test_equality(self, example_sub_file):
        """Ensure that equivalent SubtitleFile instances are equal."""
        assert example_sub_file == SubtitleFile('example.srt')


class TestStreamLabel:
    """Test the StreamLabel class."""

    def test_minimal(self):
        """Ensure that an empty StreamLabel instance has empty string attrs."""
        empty = StreamLabel()
        attrs = ['title', 'bitrate', 'resolution', 'language', 'channels',
                 'default']
        for attr in attrs:
            assert getattr(empty, attr) == ''

    def test_default(self):
        """Ensure default property is mapping properly."""
        test = StreamLabel()
        assert test.default == ''
        test.default = True
        assert test.default == 'default'
        test.default = False
        assert test.default == ''

    def test_example_audio(self, example_audio_streamlabel):
        """Ensure that args are properly mapped to attrs for the example audio
        instance."""
        attrs = {'title': 'Example Audio Stream', 'bitrate': 250,
                 'resolution': '', 'language': 'eng', 'channels': 'stereo',
                 'default': 'default'}
        for attr, value in attrs.items():
            assert getattr(example_audio_streamlabel, attr) == value

    def test_match_example_audio(self, example_audio_streamlabel):
        """Ensure that the example audio instance matches one built from
        example.json."""
        built = StreamLabel.from_dict(EXAMPLE['streams'][1])
        assert example_audio_streamlabel == built

    def test_example_video(self, example_video_streamlabel):
        """Ensure that args are properly mapped to attrs for the example video
        instance."""
        attrs = {'title': 'Example Video Stream', 'bitrate': 11.44,
                 'resolution': '214x160', 'language': 'eng', 'channels': '',
                 'default': 'default'}
        for attr, value in attrs.items():
            assert getattr(example_video_streamlabel, attr) == value

    def test_match_example_video(self, example_video_streamlabel):
        """Ensure that the example audio instance matches one built from
        example.json."""
        built = StreamLabel.from_dict(EXAMPLE['streams'][0])
        assert example_video_streamlabel == built

    def test_example_sub(self, example_sub_streamlabel):
        """Ensure that args are properly mapped to attrs for the example
        subtitle instance."""
        attrs = {'title': 'Example Subtitle Stream', 'bitrate': '',
                 'resolution': '', 'language': 'spa', 'channels': '',
                 'default': ''}
        for attr, value in attrs.items():
            assert getattr(example_sub_streamlabel, attr) == value

    def test_match_example_sub(self, example_sub_streamlabel):
        """Ensure that the example subtitle instance matches one built from
        example.json."""
        built = StreamLabel.from_dict(EXAMPLE['streams'][3])
        assert example_sub_streamlabel == built


class TestStream:
    """Test the Stream class."""

    def test_minimal(self):
        """Ensure that optional and instance  Stream attrs are properly
        instantiated."""
        built = Stream(2, 'audio', 'mp3')
        attrs = {'custom_crf': None, 'custom_bitrate': None,
                 'option_summary': None, 'labels': StreamLabel()}
        for attr, value in attrs.items():
            assert getattr(built, attr) == value

    def test_example_audio(self, example_audio_stream,
                           example_audio_streamlabel):
        """Ensure that args are properly mapped to attrs for the example audio
        instance."""
        attrs = {'index': 1, 'type': 'audio', 'codec': 'vorbis',
                 'custom_crf': None, 'custom_bitrate': None,
                 'labels': example_audio_streamlabel}
        for attr, value in attrs.items():
            assert getattr(example_audio_stream, attr) == value

    def test_match_example_audio(self, example_audio_stream):
        """Ensure that the example audio instance matches one built from
        example.json."""
        built = Stream.from_dict(EXAMPLE['streams'][1])
        assert example_audio_stream == built

    def test_example_video(self, example_video_stream,
                           example_video_streamlabel):
        """Ensure that args are properly mapped to attrs for the example video
        instance."""
        attrs = {'index': 0, 'type': 'video', 'codec': 'vp8',
                 'custom_crf': None, 'custom_bitrate': None,
                 'labels': example_video_streamlabel}
        for attr, value in attrs.items():
            assert getattr(example_video_stream, attr) == value

    def test_match_example_video(self, example_video_stream):
        """Ensure that the example audio instance matches one built from
        example.json."""
        built = Stream.from_dict(EXAMPLE['streams'][0])
        assert example_video_stream == built

    def test_example_sub(self, example_sub_stream, example_sub_streamlabel):
        """Ensure that args are properly mapped to attrs for the example
        subtitle instance."""
        attrs = {'index': 3, 'type': 'subtitle', 'codec': 'subrip',
                 'custom_crf': None, 'custom_bitrate': None,
                 'labels': example_sub_streamlabel}
        for attr, value in attrs.items():
            assert getattr(example_sub_stream, attr) == value

    def test_match_example_sub(self, example_sub_stream):
        """Ensure that the example subtitle instance matches one built from
        example.json."""
        built = Stream.from_dict(EXAMPLE['streams'][3])
        assert example_sub_stream == built


class TestStreamBuildOptions:
    """Test the Stream.build_options method."""

    def test_audio_defaults(self):
        """Ensure that default audio options are properly generated."""
        built = Stream(4, 'audio', FAKE_CODEC)
        assert built.build_options() == ['-c:a:0', defaults.C_AUDIO, '-b:a:0',
                                         str(defaults.BITRATE) + 'k']
        assert built.option_summary == ('transcode -> {}, bitrate={}Kib/s'
                                        .format(defaults.C_AUDIO,
                                                defaults.BITRATE))

    def test_audio_custom_bitrate(self):
        """Ensure that audio options are properly generated with a custom
        bitrate."""
        bitrate = 512
        built = Stream(5, 'audio', FAKE_CODEC, custom_bitrate=bitrate)
        assert built.build_options() == ['-c:a:0', defaults.C_AUDIO, '-b:a:0',
                                         str(bitrate) + 'k']
        assert built.option_summary == ('transcode -> {}, bitrate={}Kib/s'
                                        .format(defaults.C_AUDIO, bitrate))

    def test_audio_labels_bitrate(self):
        """Ensure that audio options are properly generated when using the
        labels bitrate."""
        bitrate = 256
        labels = StreamLabel(bitrate=bitrate)
        built = Stream(2, 'audio', FAKE_CODEC, labels=labels)
        assert built.build_options() == ['-c:a:0', defaults.C_AUDIO, '-b:a:0',
                                         str(bitrate) + 'k']
        assert built.option_summary == ('transcode -> {}, bitrate={}Kib/s'
                                        .format(defaults.C_AUDIO, bitrate))

    def test_audio_copy(self):
        """Ensure that audio options are properly generated for copying."""
        test = Stream(3, 'audio', defaults.C_AUDIO)
        assert test.build_options() == ['-c:a:0', 'copy']
        assert test.option_summary == 'copy'

    def test_video_defaults(self):
        """Ensure that default video options are properly generated."""
        built = Stream(1, 'video', FAKE_CODEC)
        assert built.build_options() == ['-c:v:0', 'libx264', '-preset',
                                         defaults.PRESET, '-crf',
                                         str(defaults.CRF), '-pix_fmt',
                                         'yuv420p']

    def test_video_custom_crf(self):
        """Ensure that video options are properly generated with a custom
        crf."""
        crf = 11
        built = Stream(2, 'video', FAKE_CODEC, custom_crf=crf)
        assert built.build_options() == ['-c:v:0', 'libx264', '-preset',
                                         defaults.PRESET, '-crf',
                                         str(crf), '-pix_fmt', 'yuv420p']
        assert built.option_summary == ('transcode -> {}, crf={}'
                                        .format(defaults.C_VIDEO, crf))

    def test_video_copy(self):
        """Ensure that video options are properly generated for copying."""
        built = Stream(2, 'video', defaults.C_VIDEO)
        assert built.build_options() == ['-c:v:0', 'copy']
        assert built.option_summary == 'copy'

    def test_subtitle_transcode(self):
        """Ensure that subtitle options are properly generated for
        transcoding."""
        built = Stream(1, 'subtitle', FAKE_CODEC)
        assert built.build_options() == ['-c:s:0', defaults.C_SUBS]
        assert built.option_summary == ('transcode -> {}'
                                        .format(defaults.C_SUBS))

    def test_subtitle_copy(self):
        """Ensure that subtitle options are properly generated for copying."""
        built = Stream(3, 'subtitle', defaults.C_SUBS)
        assert built.build_options() == ['-c:s:0', 'copy']
        assert built.option_summary == 'copy'

    def test_stream_ops_transcode_num(self):
        """Ensure that Stream.build_options properly includes the stream number
        when generating stream transcoding options."""
        for number in range(0, 10, 3):
            for stream_type in ['audio', 'video', 'subtitle']:
                built = Stream(number // 2, stream_type, FAKE_CODEC)
                options = built.build_options(number)
                assert options[0].split(':')[-1] == str(number)

    def test_stream_options_copy_number(self):
        """Ensure that Stream.build_options properly includes the stream number
        when generating stream copying options."""
        for number in range(0, 10, 3):
            for stream_type, default in {'audio': defaults.C_AUDIO,
                                         'video': defaults.C_VIDEO,
                                         'subtitle': defaults.C_SUBS}.items():
                built = Stream(number // 2, stream_type, default)
                options = built.build_options(number)
                assert options[0].split(':')[-1] == str(number)


class TestContainerLabel:
    """Test the ContainerLabel class."""

    def test_minimal(self):
        """Ensure that an empty ContainerLabel has empty str attrs."""
        built = ContainerLabel()
        attrs = ['title', 'size', 'bitrate', 'container_format', 'length']
        for attr in attrs:
            assert getattr(built, attr) == ''

    def test_example(self, example_container_label):
        """Ensure that args are properly mapped to attrs for the example
        instance."""
        attrs = {'title': 'Example Container', 'size': 4.94, 'bitrate': 0.21,
                 'container_format': 'Matroska / WebM',
                 'length': datetime.timedelta(0, 187)}
        for attr, value in attrs.items():
            assert getattr(example_container_label, attr) == value

    def test_match_example(self, example_container_label):
        """Ensure that the example ContainerLabel matches one built from
        example.json."""
        assert example_container_label == ContainerLabel.from_dict(EXAMPLE)


class TestContainer:
    """Test the Container class."""

    def test_minimal(self, example_audio_stream):
        """Ensure that optional and instance Container attrs are properly
        initialized."""
        built = Container('./test_film.mkv', 233.121, [example_audio_stream])
        attrs = {'subtitle_files': [], 'microseconds': 233121000,
                 'output_name': 'test_film' + defaults.ENDING,
                 'selected': [1], 'labels': ContainerLabel(), 'process': None,
                 'equality_ignore': ['temp_file', 'process']}
        for attr, value in attrs.items():
            assert getattr(built, attr) == value

    def test_temp_file(self, example_container):
        """Ensure that Container.temp_file can be written to, read from, and
        has a name attribute."""
        assert example_container.temp_file.read() == b''
        assert example_container.temp_file.write(b'') == 0
        assert bool(example_container.temp_file.name)

    def test_example(self, example_container, example_container_label,
                     example_video_stream, example_audio_stream,
                     other_audio_stream, example_sub_stream):
        """Ensure that args are properly mapped to attrs for the example
        instance."""
        attrs = {'file_name': './examplefile.ogv', 'duration': 186.727,
                 'streams': [example_video_stream, example_audio_stream,
                             other_audio_stream, example_sub_stream],
                 'subtitle_files': [], 'selected': [0, 1], 'process': None,
                 'output_name': 'examplefile' + defaults.ENDING,
                 'labels': example_container_label, 'microseconds': 186727000,
                 'equality_ignore': ['temp_file', 'process']}
        for attr, value in attrs.items():
            assert getattr(example_container, attr) == value

    def test_match_example(self, example_container):
        """Ensure that the example Container matches one built from
        example.json."""
        assert example_container == Container.from_dict(EXAMPLE)

    def test_match_example_from_file(self, example_container, monkeypatch):
        """Ensure that Container.from_file builds an instance that matches the
        example."""

        def mockreturn(commands, stdout, stderr):
            """Ensure that the ffprobe command is properly formatted. Return a
            mock ffprobe response based on example.json."""
            assert commands == [defaults.FFPROBE, '-v', 'error',
                                '-show_format', '-show_streams', '-of', 'json',
                                'example.ogv']
            with open('example.json') as example_file:
                example_text = '\n'.join(example_file.readlines())

            probe = namedtuple('probe', ['returncode', 'stdout'])
            return probe(False, example_text)

        monkeypatch.setattr(subprocess, 'run', mockreturn)
        assert example_container == Container.from_file('example.ogv')

    def test_streams_dict(self, example_container):
        """Ensure that the streams_dict property properly numbers and includes
        Streams."""
        for index, stream in example_container.streams_dict.items():
            assert stream.index == index

        for stream in example_container.streams:
            assert stream in example_container.streams_dict.values()

    def test_progress_finished(self, finished_example_container):
        """Ensure that the progress property raises ProgressFinishedError
        when transcoding has completed as evidenced by a non-None response from
        the Container.process.poll method."""
        with pytest.raises(ProgressFinishedError):
            print(finished_example_container.progress)

    def test_progress_running(self, running_example_container):
        """Ensure that the progress property can properly extract progress
        information from a running process."""
        mock_file = namedtuple('temp_file', ['name'])
        examples = {'example0.tmp': 186731950, 'example1.tmp': 38193968}
        for temp_file, progress in examples.items():
            running_example_container.temp_file = mock_file(temp_file)
            assert running_example_container.progress == progress

    def test_acceptable(self, example_container):
        """Ensure that all combinations of streams from the example Container
        are considered acceptable."""
        streams = example_container.streams_dict.keys()
        for repeat, _ in enumerate(streams):
            for index_list in permutations(streams, repeat):
                assert example_container.acceptable_streams(index_list)

    def test_acceptable_range(self, example_container):
        """Ensure that stream indexes that do not match a Stream in the example
        container are not considered acceptable."""
        streams = list(example_container.streams_dict.keys())
        cases = [[min(streams) - 1], streams + [min(streams) - 1],
                 [max(streams) + 1], streams + [max(streams) + 1]]
        for case in cases:
            with pytest.raises(ValueError):
                assert not example_container.acceptable_streams(case)

    def test_acceptable_type(self, example_container):
        """Ensure that streams with a type not in ['audio', 'video',
        'subtitle'] are not considered acceptable."""
        for stream in example_container.streams:
            assert example_container.acceptable_streams([stream.index])
            stream.type = 'data'
            with pytest.raises(ValueError):
                assert example_container.acceptable_streams([stream.index])

    def test_add_sub_file(self, example_container, example_sub_file):
        """Ensure that the Container.add_subtitle_file method properly adds a
        subtitle file."""
        assert example_container.subtitle_files == []
        example_container.add_subtitle_file('example.srt')
        assert example_container.subtitle_files == [example_sub_file]

    def test_example_build_command(self, example_container,
                                   example_audio_stream, example_video_stream):
        """Ensure that the Container.build_command method properly builds
        ffmpeg commands for the example container."""
        assert example_container.build_command() == [
            defaults.FFMPEG, '-nostdin', '-progress',
            example_container.temp_file.name, '-v', 'error', '-y', '-i',
            example_container.file_name, '-map', '0:0', '-map', '0:1',
            *example_video_stream.build_options(),
            *example_audio_stream.build_options(),
            './{}'.format(example_container.output_name)
        ]

    def test_diff_build_command(self, example_container, other_audio_stream,
                                example_sub_file, example_video_stream):
        """Ensure that the Container.build_command method properly builds
        ffmpeg commands for a tweaked container."""
        example_container.add_subtitle_file('example.srt')
        example_container.selected = [0, 2]
        assert example_container.build_command() == [
            defaults.FFMPEG, '-nostdin', '-progress',
            example_container.temp_file.name, '-v', 'error', '-y', '-i',
            example_container.file_name, '-sub_charenc', 'ascii', '-i',
            'example.srt', '-map', '0:0', '-map', '0:2', '-map', '1:0',
            *example_video_stream.build_options(),
            *other_audio_stream.build_options(),
            '-c:s:0', *example_sub_file.options,
            './{}'.format(example_container.output_name)
        ]

    def test_convert(self, monkeypatch, example_container,
                     example_audio_stream, example_video_stream):
        """Ensure that the Container.convert method calls subprocess.Popen with
        the proper arguments."""
        def mockreturn(command, stderr, universal_newlines):
            assert command == [
                defaults.FFMPEG, '-nostdin', '-progress',
                example_container.temp_file.name, '-v', 'error', '-y', '-i',
                example_container.file_name, '-map', '0:0', '-map', '0:1',
                *example_video_stream.build_options(),
                *example_audio_stream.build_options(),
                './{}'.format(example_container.output_name)
            ]
            assert stderr == subprocess.PIPE
            assert universal_newlines is True
            return True

        monkeypatch.setattr(subprocess, 'Popen', mockreturn)
        example_container.convert()
        assert example_container.process is True
