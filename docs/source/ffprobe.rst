ffprobe JSON Format
===================

filmalize uses ffprobe to extract metadata from multimedia container files in
order to automatically generate instances using the :any:`Container.from_file`
factory. The api that filmalize queries is ffprobe's `json writer`_, to which 
the '-show_streams' and '-show_format' flags are passed. Unfortunately, unlike
the xml writer, which comes with a handy full `spec`_ definition, the json
writer's output structure is undocumented. Fortunately, it is quite easy to
explore and work with. In the interest of clarity (sanity), I have reproduced
below the structure and values that are relevant to filmalize.

Note that there are many other entries that have not been included as they are
not used by filmalize at this time. Furthermore, ffprobe will not include
entries in its output if it doesn't find the relevant info when probing a file.
Therefore, filmalize is designed to be resiliant to recieving very minimal
information. When creating an instance using the :obj:`from_dict` factory,
:any:`Container` only requires 'filename', 'duration' and 'stream' entries.
Similarly, :any:`Stream` only requires 'index' and 'codec_type' entries.

Example ffprobe json output
---------------------------

(Stripped of non-essential entries.)

.. literalinclude:: ../../tests/example.json
   :language: json

.. _json writer: https://ffmpeg.org/ffprobe.html#json
.. _spec: https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/doc/ffprobe.xsd
