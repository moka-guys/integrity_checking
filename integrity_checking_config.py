"""
integrity_checking configuration script.

Variables defined in this module are required by sequencer_checksum.py.
"""
# Set debug mode
#debug = True
debug = False

# =====git release for the github repo=====
script_release = "v22.0"

# ================ Integrity check
# the filename which holds the checksum results
md5checksum_name = "md5checksum.txt"
# checksum complete statement
checksum_complete_flag = "Checksum result reported"
# statement to write when checksums match
checksum_match = "Checksums match"
# hours to wait after RTAcomplete.txt file before first integrity check 
integrity_check_first_wait = 3
# hours between integrity checks
integrity_check_repeat_wait = 1
# maximum number of times to perform integrity test
max_number_of_attempts = 10
# list of files which differ between temp and output
missing_files_output = "missing_files.txt"
# files to exclude from integrity check
exclude = ["RTAStart.bat", "CorrectedIntMetrics.bin", "EmpiricalPhasingMetrics.bin", "ErrorMetrics.bin", "EventMetrics.bin", "ExtractionMetrics.bin", "PFGridMetrics.bin", "QMetrics.bin", "RegistrationMetrics.bin", "TileMetrics.bin", "AlignmentMetrics.bin", "BasecallingMetrics.bin", "ExtendedTileMetrics.bin", "FWHMGridMetrics.bin", "ImageMetrics.bin", "QGridMetrics.bin", "000_000_000_na_rtabat.trans", "FilesAdded.csv", "FilesCopied.csv", "md5checksum.txt", missing_files_output]

