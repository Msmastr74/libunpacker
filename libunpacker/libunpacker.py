import os
import zipfile
import tarfile
import rarfile # Listen man, I know it's a dependency, but the alternative is spending a couple weeks building a virtual machine and some other bullshit like that that someone has already done, so don't gripe at me about it!
import gzip
import bz2
import lzma
from io import BytesIO
from pathlib import Path

verbose = False  # So that users can use libunpacker.verbose = True for debugging 

UNRAR_INSTALL_WIN_TUTORIAL = """

libunpacker requires a valid UnRAR executable to unpack .rar archives
UnRAR was not found within your systems PATH environment variables
To install UnRAR and add it to PATH, here's a simple tutorial:
1. Install UnRAR from RARLAB at https://www.rarlab.com/rar_add.htm
2. Open the start menu search bar, type 'env' then select 'Edit the system environment variables' then press the 'Environment Variables' button in the bottom right
3. Under System variables select Path, then click Edit, then click New, and paste the path to the parent directory of your UnRAR.exe file and press enter, then click OK on all three open windows to save your changes
4. Restart the terminal or your IDE to make your changes take effect
Now run the program again to hopefully not get this message again, if you do just run through steps 2-4 again and make sure you did everything right, if you did everything right yet still get this message, check your code to ensure nothing is causing the issue there (check your dependencies as well to see if they're causing the issue), and if you still can't find anything that may be causing the issue, submit an issue at https://github.com/msmastr74/libunpacker

"""

class LibunpackerError(Exception):
    """Base exception for the unpacker library. All other errors inherit from this."""
    pass

class InvalidDataError(LibunpackerError):
    """Raised when pseudo-protocols like //data: are malformed."""
    pass

class UnsupportedFormatError(LibunpackerError):
    """Raised when a file format isn't recognized by the magic byte scanner."""
    pass

class ExtractionError(LibunpackerError, zipfile.BadZipFile, tarfile.ReadError, lzma.LZMAError, rarfile.Error):
    """Raised when an archive is corrupted or password-protected."""
    pass

class LibunpackerFileNotFoundError(LibunpackerError, FileNotFoundError):
    """Raised when an archive path is missing. Inherits from both LibunpackerError and FileNotFoundError."""
    pass

class LibunpackerFileExistsError(LibunpackerError, FileExistsError):
    """Raised when a file already exists. Inherits from both LibunpackerError and FileExistsError."""
    pass

class LibunpackerNotADirectoryError(LibunpackerError, NotADirectoryError):
    """Raised when trying to unpack to a non-existent directory"""
    pass

class LibunpackerIsADirectoryError(LibunpackerError, IsADirectoryError):
    """Raised when monofiles are unpacked to directories"""

def get_format(data: bytes):
    FORMAT_MAP = {
        b"PK\x03\x04": "zip",
        b"7z\xbc\xaf'\x1c": "_7z",
        b"\x1f\x8b": "gzip",
        b"BZh": "bzip2",
        b"\xfd7zXZ\x00": "xz",
        b"Rar!\x1a\x07": "rar",
    }
    
    # Check magic bytes; bzip2 uses 3 bytes ("BZh")
    for magic, fmt in FORMAT_MAP.items():
        if data.startswith(magic):
            if verbose: print(f"Format: {fmt}")
            return fmt
            
    # Fallback for tar detection
    if len(data) > 262 and data[257:262] == b"ustar":
        if verbose: print("Format: tar")
        return "tar"
    
    if verbose: print("Format: None")
    return None


class unpackers:
    def zip(data: bytes):
        # Raw data extractor for zip files, definitely one of the easiest unpackers to make
        rawdata = BytesIO(data)
        
        unpacked_zip = {}
        try:
            with zipfile.ZipFile(rawdata, "r") as archive:
                if verbose: print(f"zip: Packed files: {archive.namelist()}")
                for filename in archive.namelist():
                    if verbose: print(f"zip: Unpacking: {filename}")
                    with archive.open(filename) as file_zipped:
                        unpacked_zip[filename] = file_zipped.read()
        except zipfile.BadZipFile:
            raise ExtractionError("ZIP archive either corrupted or password-protected")
        return unpacked_zip
    
    def tar(data: bytes):
        # Adding support for tar files is the easy part, the hard part is gonna be detecting it
        # Nevermind, detection added
        rawdata = BytesIO(data)
            
        unpacked_tar = {}
        try:
            with tarfile.open(fileobj=rawdata, mode="r") as archive:
                if verbose: print(f"tar: Packed files: {archive.getnames()}")
                for member in archive.getmembers():
                    if verbose: print(f'tar: Unpacking: {member.name}')
                    if member.isfile():
                        with archive.extractfile(member) as file_tarred:
                            unpacked_tar[member.name] = file_tarred.read()
        except (tarfile.TarError, tarfile.ReadError):
            raise ExtractionError("TAR archive is either corrupted, unreadable, or invalid")
        return unpacked_tar
    
    def _7z(data: bytes):
        # All my homies hate writing a 7z interpreter
        preheader = data[:32]
        
        next_header_offset = int.from_bytes(preheader[12:20], byteorder="little")
        next_header_size = int.from_bytes(preheader[20:28], byteorder="little")
        
        main_header = data[32+next_header_offset:32+next_header_offset+next_header_size]
        
        def read_vli(b, pos):
            first = b[pos]
            pos += 1
            mask = 0x80
            extra = 0
            while first & mask:
                extra += 1
                mask >>= 1
            if extra < 8:
                value = first & (mask - 1)
                value <<= (8 * extra)
                for i in range(extra):
                    value |= (b[pos] << (8 * (extra - 1 - i)))
                    pos += 1
            else:
                value = 0
                for i in range(8):
                    value |= (b[pos] << (8 * i))
                    pos += 1
            return value, pos

        # Dynamic raw stream decoder that uses max_length to tolerate missing/extra EOS markers
        def decode_stream(compressed, codec, props, uncompressed_size):
            max_sz = uncompressed_size if (uncompressed_size and uncompressed_size > 0) else 2**30
            if codec == b'\x21': # LZMA2
                prop = props[0] if props else 0
                dict_size = (2 | (prop & 1)) << (prop // 2 + 11) if prop < 40 else 0xFFFFFFFF
                try:
                    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}])
                    return dec.decompress(compressed, max_length=max_sz)
                except Exception:
                    return lzma.decompress(compressed, format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}])
            elif codec == b'\x03\x01\x01' or codec == b'\x03': # LZMA1
                if len(props) == 5:
                    d = props[0]
                    lc = d % 9
                    d //= 9
                    lp = d % 5
                    pb = d // 5
                    dict_size = int.from_bytes(props[1:5], byteorder="little")
                    try:
                        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{
                            "id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb, "dict_size": dict_size
                        }])
                        return dec.decompress(compressed, max_length=max_sz)
                    except Exception:
                        pass
                    header = props + max_sz.to_bytes(8, "little")
                    try:
                        return lzma.decompress(header + compressed, format=lzma.FORMAT_ALONE)
                    except lzma.LZMAError:
                        pass
            # Fallback to standard container decompressions
            try:
                return lzma.decompress(compressed)
            except lzma.LZMAError:
                pass
            try:
                return lzma.decompress(compressed, format=lzma.FORMAT_ALONE)
            except lzma.LZMAError:
                pass
            try:
                return lzma.decompress(compressed, format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2}])
            except lzma.LZMAError:
                raise ExtractionError("LZMA compressed 7z stream is corrupted or invalid")

        if main_header and main_header[0] == 0x17:
            pos = 1
            h_codec = b''
            h_props = b''
            h_unpack_sizes = []
            pack_pos = 0
            pack_sizes = []
            
            # Robust property parser loop for the compressed header block
            while pos < len(main_header):
                h_type = main_header[pos]
                pos += 1
                if h_type == 0x00:
                    continue
                elif h_type == 0x06:  # kPackInfo
                    pack_pos, pos = read_vli(main_header, pos)
                    num_pack_streams, pos = read_vli(main_header, pos)
                    if main_header[pos] == 0x09:
                        pos += 1
                        for _ in range(num_pack_streams):
                            sz, pos = read_vli(main_header, pos)
                            pack_sizes.append(sz)
                    while pos < len(main_header) and main_header[pos] != 0x00:
                        pos += 1
                    pos += 1
                elif h_type == 0x07:  # kUnpackInfo
                    if main_header[pos] == 0x0B:  # kFolder
                        pos += 1
                        num_folders, pos = read_vli(main_header, pos)
                        pos += 1
                        for _ in range(num_folders):
                            num_coders, pos = read_vli(main_header, pos)
                            for _ in range(num_coders):
                                flags = main_header[pos]
                                pos += 1
                                codec_size = flags & 0x0F
                                h_codec = main_header[pos : pos + codec_size]
                                pos += codec_size
                                if flags & 0x10:
                                    _, pos = read_vli(main_header, pos)
                                    _, pos = read_vli(main_header, pos)
                                if flags & 0x20:
                                    props_size, pos = read_vli(main_header, pos)
                                    h_props = main_header[pos : pos + props_size]
                                    pos += props_size
                            if num_coders > 1:
                                for _ in range(num_coders - 1):
                                    _, pos = read_vli(main_header, pos)
                                    _, pos = read_vli(main_header, pos)
                    if pos < len(main_header) and main_header[pos] == 0x0C:  # kCodersUnpackSize
                        pos += 1
                        for _ in range(num_folders):
                            upsz, pos = read_vli(main_header, pos)
                            h_unpack_sizes.append(upsz)
                    while pos < len(main_header) and main_header[pos] != 0x00:
                        pos += 1
                    pos += 1
                elif h_type == 0x08:  # kSubStreamsInfo
                    while pos < len(main_header) and main_header[pos] != 0x00:
                        pos += 1
                    pos += 1
            
            pack_size = sum(pack_sizes)
            compressed_header_stream = data[32 + pack_pos : 32 + pack_pos + pack_size]
            h_upsz = h_unpack_sizes[0] if h_unpack_sizes else 0
            try:
                main_header = decode_stream(compressed_header_stream, h_codec, h_props, h_upsz)
            except Exception:
                raise ExtractionError("LZMA compressed 7z header stream is corrupted or invalid")
        
        pos = 0
        if pos < len(main_header) and main_header[pos] == 0x01:
            pos += 1

        pack_pos = 0
        pack_sizes = []
        folder_unpack_sizes = []
        file_sizes = []
        file_names = []
        empty_stream_flags = []
        saved_codec = b''
        saved_props = b''

        while pos < len(main_header):
            type_id = main_header[pos]
            pos += 1
            
            if type_id == 0x00:
                continue
            elif type_id == 0x04:  # kMainStreamsInfo
                continue
            elif type_id == 0x06:  # kPackInfo
                pack_pos, pos = read_vli(main_header, pos)
                num_pack_streams, pos = read_vli(main_header, pos)
                if main_header[pos] == 0x09:
                    pos += 1
                    for _ in range(num_pack_streams):
                        sz, pos = read_vli(main_header, pos)
                        pack_sizes.append(sz)
                    while pos < len(main_header) and main_header[pos] != 0x00:
                        pos += 1
                    pos += 1
            elif type_id == 0x07:  # kUnpackInfo
                if main_header[pos] == 0x0B:  # kFolder
                    pos += 1
                    num_folders, pos = read_vli(main_header, pos)
                    pos += 1
                    for _ in range(num_folders):
                        num_coders, pos = read_vli(main_header, pos)
                        for _ in range(num_coders):
                            flags = main_header[pos]
                            pos += 1
                            codec_size = flags & 0x0F
                            saved_codec = main_header[pos : pos + codec_size]
                            pos += codec_size
                            if flags & 0x10:
                                _, pos = read_vli(main_header, pos)
                                _, pos = read_vli(main_header, pos)
                            if flags & 0x20:
                                props_size, pos = read_vli(main_header, pos)
                                saved_props = main_header[pos : pos + props_size]
                                pos += props_size
                        if num_coders > 1:
                            for _ in range(num_coders - 1):
                                _, pos = read_vli(main_header, pos)
                                _, pos = read_vli(main_header, pos)
                if pos < len(main_header) and main_header[pos] == 0x0C:  # kCodersUnpackSize
                    pos += 1
                    for _ in range(num_folders):
                        upsz, pos = read_vli(main_header, pos)
                        folder_unpack_sizes.append(upsz)
                while pos < len(main_header) and main_header[pos] != 0x00:
                    pos += 1
                pos += 1
            elif type_id == 0x08:  # kSubStreamsInfo
                num_unpack_streams_list = []
                if main_header[pos] == 0x0D:
                    pos += 1
                    for _ in range(len(folder_unpack_sizes)):
                        num_str, pos = read_vli(main_header, pos)
                        num_unpack_streams_list.append(num_str)
                else:
                    num_unpack_streams_list = [1] * len(folder_unpack_sizes)
                
                if pos < len(main_header) and main_header[pos] == 0x09:
                    pos += 1
                    for idx, num_str in enumerate(num_unpack_streams_list):
                        running_sum = 0
                        for _ in range(num_str - 1):
                            sz, pos = read_vli(main_header, pos)
                            file_sizes.append(sz)
                            running_sum += sz
                        if idx < len(folder_unpack_sizes):
                            file_sizes.append(folder_unpack_sizes[idx] - running_sum)
                else:
                    file_sizes.extend(folder_unpack_sizes)
                while pos < len(main_header) and main_header[pos] != 0x00:
                    pos += 1
                pos += 1
            elif type_id == 0x05:  # kFilesInfo
                num_files, pos = read_vli(main_header, pos)
                while pos < len(main_header):
                    prop_id = main_header[pos]
                    pos += 1
                    if prop_id == 0x00:
                        break
                    size, pos = read_vli(main_header, pos)
                    next_prop_pos = pos + size
                    
                    if prop_id == 0x11:  # kName
                        pos += 1
                        file_names = []
                        for _ in range(num_files):
                            name_bytes = bytearray()
                            while pos < next_prop_pos:
                                char_bytes = main_header[pos:pos+2]
                                pos += 2
                                if char_bytes == b"\x00\x00" or len(char_bytes) < 2:
                                    break
                                name_bytes.extend(char_bytes)
                            file_names.append(name_bytes.decode("utf-16-le"))
                    elif prop_id == 0x0E:  # kEmptyStream
                        bytes_to_read = (num_files + 7) // 8
                        bits = main_header[pos:pos+bytes_to_read]
                        for i in range(num_files):
                            empty_stream_flags.append(((bits[i // 8] >> (7 - (i % 8))) & 1) == 1)
                    pos = next_prop_pos

        if pack_sizes:
            compressed_data = data[32 + pack_pos : 32 + pack_pos + sum(pack_sizes)]
            try:
                upsz = folder_unpack_sizes[0] if folder_unpack_sizes else 0
                uncompressed_payload = decode_stream(compressed_data, saved_codec, saved_props, upsz)
            except Exception:
                raise ExtractionError("LZMA compressed 7z data stream is corrupted or invalid")
        else:
            uncompressed_payload = b""

        unpacked_7z = {}
        size_idx = 0
        payload_ptr = 0

        if not empty_stream_flags:
            empty_stream_flags = [False] * len(file_names)

        if verbose: print(f"7z: Packed files: {file_names}")

        for i, name in enumerate(file_names):
            if verbose: print(f"7z: Unpacking: {name}")
            if i < len(empty_stream_flags) and empty_stream_flags[i]:
                unpacked_7z[name] = b""
            else:
                if size_idx < len(file_sizes):
                    sz = file_sizes[size_idx]
                    size_idx += 1
                    unpacked_7z[name] = uncompressed_payload[payload_ptr : payload_ptr + sz]
                    payload_ptr += sz
                else:
                    unpacked_7z[name] = b""
                    
        return unpacked_7z
    
    def gzip(data: bytes):
        try:
            if verbose: print("gzip: Unpacking datastream")
            return {"file": gzip.decompress(data)}
        except Exception:
            raise ExtractionError("GZIP file is either corrupted, unreadable, or invalid")
    
    def bzip2(data: bytes):
        try:
            if verbose: print("bzip2: Unpacking datastream")
            return {"file": bz2.decompress(data)}
        except Exception:
            raise ExtractionError("BZIP2 file is either corrupted, unreadable, or invalid")
    
    def xz(data: bytes):
        # Decided to make this one while making 7z, to make it easier to decode 7z blocks
        try:
            if verbose: print("xz: Attempting headed LZMA2 unpacking")
            return {"file": lzma.decompress(data)}
        except lzma.LZMAError:
            if verbose: print("xz: Failed")
        
        try:
            if verbose: print("xz: Attempting headed LZMA unpacking")
            return {"file": lzma.decompress(data, format=lzma.FORMAT_ALONE)}
        except lzma.LZMAError:
            if verbose: print("xz: Failed")
        
        try:
            if verbose: print("xz: Attempting unheaded LZMA unpacking")
            return {"file": lzma.decompress(data, format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1}])}
        except (lzma.LZMAError, ValueError):
            if verbose: print("xz: Failed")
        
        try:
            if verbose: print("xz: Attempting unheaded LZMA2 unpacking")
            return {"file": lzma.decompress(data, format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2}])}
        except (lzma.LZMAError, ValueError):
            if verbose: print("xz: All attempts failed, raising error")
            raise ExtractionError("LZMA compressed file is either corrupted, unreadable, or invalid")
    
    def rar(data: bytes):
        # I was actually dreading this, but then I decided to bite the bullet and have a dependency to save me countless hours of building a RAR decompressor
        rawdata = BytesIO(data)
        
        unpacked_rar = {}
        try:
            with rarfile.RarFile(rawdata, "r") as archive:
                if verbose: print(f"rar: Packed files: {archive.namelist()}")
                for filename in archive.namelist():
                    if verbose: print(f"rar: Unpacking: {filename}")
                    with archive.open(filename) as file_rarred:
                        unpacked_rar[filename] = file_rarred.read()
        except rarfile.BadRarFile:
            raise ExtractionError("RAR archive is either corrupted, unreadable, or invalid")
        except rarfile.PasswordRequired:
            raise ExtractionError("RAR archive is password protected, libunpacker doesn't yet have password support")
        except rarfile.RarCannotExec:
            raise ExtractionError(UNRAR_INSTALL_WIN_TUTORIAL if os.name == "nt" else "Please install unrar with your local package manager to unpack .rar archives")
        return unpacked_rar

def unpack(f_input, out_point):
    if isinstance(out_point, Path):
        # oh hey look pathlib support
        out_point = str(out_point)
    
    CMD_IN = (b"//data",)
    CMD_OUT = ("//return", "//overwrite", "//autocreate")
    
    is_cmd_in = False
    for cmd in CMD_IN:
        if isinstance(f_input, bytes) and f_input.startswith(cmd):
            is_cmd_in = True
        elif isinstance(f_input, str) and f_input.startswith(cmd.decode()):
            is_cmd_in = True
    
    is_cmd_out = False
    for cmd in CMD_OUT:
        if out_point.startswith(cmd):
            is_cmd_out = True
    
    if is_cmd_in:
        if isinstance(f_input, bytes):
            if not f_input.startswith(b"//data:"):
                raise InvalidDataError("Raw data input malformed\nProper formatting: //data:<raw file data>")
            f_data = f_input.removeprefix(b"//data:")
        else:
            if not f_input.startswith("//data:"):
                raise InvalidDataError("Raw data input malformed\nProper formatting: //data:<raw file data>")
            f_data = f_input.removeprefix("//data:").encode('latin-1') 
    else:
        try:
            with open(f_input, "rb") as f:
                f_data = f.read()
        except FileNotFoundError:
            raise LibunpackerFileNotFoundError("To pass in raw file data, use //data:<file data>")
    
    f_format = get_format(f_data)
    unpacked_data_temp = f_data
    unpacks = 0
    while True:
        if f_format is None:
            if unpacks == 0:
                raise UnsupportedFormatError("File is either not archived, top-level archive is in an unsupported format, or the file is corrupted")
            break
            
        unpacker_func = getattr(unpackers, f_format)
        
        if isinstance(unpacked_data_temp, dict):
            unpacked_data_temp = next(iter(unpacked_data_temp.values()))
            
        unpacked_data_temp = unpacker_func(unpacked_data_temp)
        unpacks += 1
        
        monofile = True if len(unpacked_data_temp) == 1 else False
        
        if not monofile:
            break
            
        if isinstance(unpacked_data_temp, bytes):
            f_format = get_format(unpacked_data_temp)
        else:
            f_format = get_format(next(iter(unpacked_data_temp.values())))

    unpacked_data = next(iter(unpacked_data_temp.values())) if isinstance(unpacked_data_temp, dict) and monofile else unpacked_data_temp
    
    if is_cmd_out and out_point.startswith("//return"):
        return unpacked_data
    elif is_cmd_out and out_point.startswith("//overwrite:") and monofile:
        with open(out_point.removeprefix("//overwrite:"), "wb") as f:
            f.write(unpacked_data)
        return "Success"
    elif is_cmd_out and out_point.startswith("//autocreate") and monofile:
        raise InvalidDataError("//autocreate cannot be used with single-file archives")
    elif monofile:
        try:
            with open(out_point, "xb") as f:
                f.write(unpacked_data)
            return "Success"
        except FileExistsError:
            raise LibunpackerFileExistsError(f"If you wish to overwrite the selected file, use //overwrite:{out_point} instead of {out_point}")
        except IsADirectoryError:
            raise LibunpackerIsADirectoryError("Can't write monofile archives to directories")
    else:
        autocreate = False
        if out_point.startswith("//autocreate:"):
            autocreate = True
            out_point = out_point.removeprefix("//autocreate:")
        elif out_point.startswith("//autocreate"):
            raise InvalidDataError("Autocreate operator malformed\nProper formatting: //autocreate:<path>")
        curr_dir = Path(out_point)
        if autocreate:
            try:
                curr_dir.mkdir()
            except Exception:
                pass
        if not curr_dir.is_dir(): 
            raise LibunpackerNotADirectoryError("Output location is either a file or non-existent, use //autocreate:<directory> to automatically create the directory")
        
        for file in unpacked_data:
            file_path = curr_dir / file
            if file.endswith("/"):
                file_path.mkdir(parents=True, exist_ok=True)
            else:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(unpacked_data[file])
        return "Success"
