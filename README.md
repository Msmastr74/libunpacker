# libunpacker
[![PyPI - Version](https://img.shields.io/pypi/v/libunpacker)](https://pypi.org/project/libunpacker/)
![License](https://img.shields.io/badge/license-MIT-blue)
![PyPI downloads](https://img.shields.io/pypi/dm/libunpacker)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/Msmastr74/libunpacker/python-publish.yml)

A multi-format archive unpacking utility supporting deep recursion.

## How to use it
The simplest way to use it that can be used in almost any use case, is simply `libunpacker.unpack(input_file_name, output_file_name)`, this will take `input_file_name` and write it's uncompressed contents to `output_file_name`. However with multi-file archives, `output_file_name` must be a directory (ending with a /, this is mandatory)
### Operators
A fun little thing I added to this is operators, these allow you to have special functionality without doing some crazy weird tricks and workarounds so here they are:
#### input (arg 1)
- `//data:<raw file data>`: rather than reading a file for the data, it takes it directly from your input!

#### output (arg 2)
- `//return`: instead of writing the uncompressed file data, it returns it
- `//overwrite:<file path>`: by default, it uses "xb" instead of "wb" for file writing, this makes it use "wb" (cannot be used on directories)
- `//autocreate:<directory path>`: by default, it doesn't write to directories that don't exist, this makes it create directories that don't exist and continue on like normal

## The unpackers class
This is what actually does the unpacking, the unpack function just handles the reading recursion and writing, although all of these functions require raw byte data as input and always return a dictionary containing the extracted data
(fun little quirk I gotta include here, unpackers.xz() can handle LZMA1 compression, but unpack() can't)

yeah that's pretty much everything you need to know to use this thing, here's my testing script that demonstrates how it's actually used and all the supported formats for all you visual learners out there:
```python
up.unpack("libunpacker_test_zip.zip", "ziptest/")
up.unpack("libunpacker_test_gzip.txt.gz", "gztest.txt")
up.unpack("libunpacker_test_bz2.txt.bz2", "bz2test.txt")
up.unpack("libunpacker_test_xz.txt.xz", "xztest.txt")
up.unpack("libunpacker_test_7z.7z", "7ztest/")
up.unpack("libunpacker_test_tar.tar", "tartest/")
up.unpack("libunpacker_test_rar.rar", "rartest/")
up.unpack("libunpacker_test_targz.tar.gz", "tgztest/")
up.unpack("libunpacker_test_big_one.tar.zip.7z.rar.gz.bz2.xz", "bigtest/")
up.unpack("libunpacker_test_big_one_disguised", "bigtest2/")
with open("libunpacker_test_lzma.txt.lzma", "rb") as f:
    lzma_file_data = up.unpackers.xz(f.read())
with open("lzmatest.txt", "wb") as f:
    f.write(lzma_file_data["file"])
# monofile testing
up.unpack("libunpacker_test_zip_mono.txt.zip", "zipmonotest.txt")
up.unpack("libunpacker_test_7z_mono.txt.7z", "7zmonotest.txt")
up.unpack("libunpacker_test_tar_mono.txt.tar", "tarmonotest.txt")
up.unpack("libunpacker_test_rar_mono.txt.rar", "rarmonotest.txt")
return_data = up.unpack("libunpacker_test_xz.txt.xz", "//return")
print(return_data)
with open("libunpacker_test_xz.txt.xz", "rb") as f:
    up.unpack(b"//data:" + f.read(), "datainputtest.txt")
up.unpack("libunpacker_test_xz.txt.xz", "//overwrite:datainputtest.txt")
up.unpack("libunpacker_test_zip.zip", "//autocreate:newdir/")
```
oh and if you're debugging, `libunpacker.verbose == True` makes it print out some runtime debugging info, it was useful for me