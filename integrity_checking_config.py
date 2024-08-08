"""
integrity_checking configuration script.

Variables defined in this module are required by sequencer_checksum.py.
"""

# ===== git release for the github repo =====
script_release = "v25.0.1"

# ===== Integrity check =====
# the filename which holds the checksum results
md5checksum_name = "md5checksum.txt"
# checksum complete statement
checksum_complete_flag = "Checksum result reported"
# statement to write when checksums match
checksum_match = "Checksums match"
# hours to wait after RTAcomplete.txt file before first integrity check
integrity_check_first_wait = 0.5
# hours between integrity checks
integrity_check_repeat_wait = 0.5
# maximum number of times to perform integrity test
max_number_of_attempts = 5
# list of files which differ between temp and output
missing_files_output = "missing_files.txt"

# ===== Platform specific settings =====
novaseq = False
nextseq = True

# list of files to exclude from the checksum calculation the 
exclude = ["IndexMetricsOut.bin", "RTAStart.bat", "CorrectedIntMetrics.bin", "EmpiricalPhasingMetrics.bin", "ErrorMetrics.bin", "EventMetrics.bin", "ExtractionMetrics.bin", "PFGridMetrics.bin", "QMetrics.bin", "RegistrationMetrics.bin", "TileMetrics.bin", "AlignmentMetrics.bin", "BasecallingMetrics.bin", "ExtendedTileMetrics.bin", "FWHMGridMetrics.bin", "ImageMetrics.bin", "QGridMetrics.bin", "000_000_000_na_rtabat.trans", "FilesAdded.csv", "FilesCopied.csv", "demultiplexlog.txt", "DNANexus_upload_started.txt", "CopyComplete.txt","bcl2fastq2_output.log", "md5checksum.txt", "sscheck_flagfile.txt", missing_files_output]

if nextseq:
    # files to exclude from integrity check
    sequencer_temp_folder = "D:\\Illumina\\NextSeq Control Software Temp"
    mapped_workstation_folder = "Z:\\"
elif novaseq:
    include = ["InterOp","Thumbnail_Images","Data"]
    sequencer_temp_folder = "Z:\\outputfolder"
    mapped_workstation_folder = "Y:\\"
