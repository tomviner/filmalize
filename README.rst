Introduction
------------

Named a `portmanteau word`_ composed of *film* and *standardize*,
filmalize is a tool for standardizing a video library. filmalize is
built with `Click`_ for python 3.4+ and also depends on the `bitmath`_,
`chardet`_, `blessed`_, and `progressbar2`_ libraries. filmalize uses
`ffmpeg`_ for all of the actual probing and converting.

I plan to expand it to produce other container formats, but at the
moment filmalize is set up to produce `mp4`_ containers, with `h264`_
video, `aac`_ audio, and `mov_text`_ subtitle streams. I chose these
parameters since I wrote filmalize to prepare videos for a site that
uses `flowplayer`_, and this combination allows for maximal end-user
compatibility in a single file format.

Get Started
-----------

Check out the documentation over at `Read The Docs`_!

.. _portmanteau word: https://en.wikipedia.org/wiki/Portmanteau
.. _Click: http://click.pocoo.org/6/
.. _bitmath: http://bitmath.readthedocs.io/en/latest/
.. _chardet: http://chardet.readthedocs.io/en/latest/
.. _ffmpeg: https://www.ffmpeg.org/
.. _mp4: https://en.wikipedia.org/wiki/MPEG-4_Part_14
.. _h264: https://en.wikipedia.org/wiki/H.264/MP
.. _aac: https://en.wikipedia.org/wiki/Advanced_Audio_Coding
.. _mov_text: https://en.wikibooks.org/wiki/FFMPEG_An_Intermediate_Guide/subtitle_options#Set_Subtitle_Codec
.. _flowplayer: https://flowplayer.org/docs/setup.html#video-formats
.. _blessed: http://blessed.readthedocs.io/en/latest/
.. _progressbar2: http://progressbar-2.readthedocs.io/en/latest/
.. _Read the Docs: http://filmalize.readthedocs.io/
