from checksumdir import dirhash # package to calculate checksums
import os # package to use and manipulate file paths
import datetime # for timestamp
import time # for sleep
import Tkinter # to open a window/message box
import tkMessageBox
import threading # to run a function in the background
import integrity_checking_config as config
import argparse

class Sequencer_Integrity_Check():
	def __init__(self):

		# temp folder on the nextseq
		self.sequencer_temp_folder = config.sequencer_temp_folder

		# path to the mapped workstation share
		self.mapped_workstation_folder = config.mapped_workstation_folder

		# the filename which denote sequencing has finished
		self.RTA_complete = "RTAComplete.txt"

		# the file to write the checksums to
		self.output_file = "md5checksum.txt"

		# folder containing files which denote checksum is being calculated
		self.checksum_in_progress = "C:\\Users\\sbsuser\\integrity_check\\checksums_inprogress"

		# folder containing files which denote checksum is being calculated
		self.run_in_progress = "C:\\Users\\sbsuser\\integrity_check\\run_inprogress"

		# variable to hold the name of the runfolder
		self.runfolder = ""

		# variables for the runfolder paths
		self.workstation_runfolder = ""
		self.sequencer_runfolder = ""

		# checksums match
		self.checksum_match = False

		# variable to hold debug status
		self.debug = False
		self.verbose = False

		# flag to override the minimum wait
		self.no_min_wait = False

		# dict to hold checksums
		self.checksum_results = {}

	def debug_mode(self):
		# if testing, overwrite the paths to that of the testing folders 
		if self.debug:
			print "debug on. Setting up test runfolders so integrity check fails"
			# example run folders that can be used to test the script are within this repo. However to enable this to be tested on multiple machines need to capture the path to this script.
			self.mapped_drive = os.path.dirname(os.path.realpath(__file__))
			# path to the fake nextseqtemp folder
			self.sequencer_temp_folder = os.path.join(self.mapped_drive,"testing_data","sequencer_temp")
			# path to the fake workstation folder
			self.mapped_workstation_folder = os.path.join(self.mapped_drive,"testing_data","workstation")
			# path to the fake checksums_inprogress folder
			self.checksum_in_progress = os.path.join(self.mapped_drive,"testing_data","checksums_inprogress")
			# path to the fake run in progress folder
			self.run_in_progress = os.path.join(self.mapped_drive,"testing_data","run_inprogress")
			
			# set up test environment:
			# move files out of folder to make integrity test fail
			if config.nextseq:
				temp_dir_path=os.path.join(self.mapped_drive,"testing_data","workstation","run100_temp")
				if not os.path.exists(temp_dir_path):
						os.mkdir(temp_dir_path)
				file_to_move=os.listdir(os.path.join(self.mapped_drive,"testing_data","workstation","run100"))[0]
				if self.verbose:
					print "moving %s to %s" %(os.path.join(self.mapped_drive,"testing_data","workstation","run100",file_to_move), os.path.join(temp_dir_path,file_to_move))
				os.rename(os.path.join(self.mapped_drive,"testing_data","workstation","run100",file_to_move), os.path.join(temp_dir_path,file_to_move))
			elif config.novaseq:
				for dir in config.include:
					temp_dir_path=os.path.join(self.mapped_drive,"testing_data","workstation",dir + "_temp")
					if not os.path.exists(temp_dir_path):
						os.mkdir(temp_dir_path)
					file_to_move=os.listdir(os.path.join(self.mapped_drive,"testing_data","workstation","run100", dir))[0]
					if self.verbose:
						print "moving %s to %s" % (os.path.join(self.mapped_drive,"testing_data","workstation","run100", dir, file_to_move),os.path.join(temp_dir_path, file_to_move))
					os.rename(os.path.join(self.mapped_drive,"testing_data","workstation","run100", dir, file_to_move),os.path.join(temp_dir_path, file_to_move))

	def look_for_folder(self):
		"""
		This script runs every hour.
		The script needs to detect when a run has started, and display a window which remains until the integrity test has been performed.
		Display a window to say not to do anything until sequencing is complete and integrity checks done.
		When checksums are done, display a message box displaying pass/fail messages.
		"""

		# for each runfolder in temp folder
		for temp_runfolder in os.listdir(self.sequencer_temp_folder):
			# if the run has not already been monitored by this script OR it's a testing run
			if temp_runfolder not in os.listdir(self.run_in_progress) or self.debug:
				# if testing print message
				if self.debug:
					print "testing run skipping test to see if run already being monitored"


				# assign run folder name
				self.runfolder = temp_runfolder
				# create a file to denote this run is being monitored
				with open(os.path.join(self.run_in_progress,temp_runfolder),'w') as new_run_marker:
					# write timestamp to file
					new_run_marker.write(str(datetime.datetime.now()))

				# call function which opens a window to say run in progress - don't do anything until a message box appears denoting integrity check has been performed
				# this function will close when the run ends and the checksum has been calculated
				self.open_window()

				# call function to assess result of checksum and display message box
				# if checksums match (integrity test pass) return a info box
				if self.checksum_match:
					# create root window which can then be hidden
					root = Tkinter.Tk()
					# hide
					root.withdraw()
					tkMessageBox.showinfo("%s Integrity check complete" % self.runfolder,"Integrity check passed" )
					# if checksums don't match (integrity test FAIL) return a error box
				else:
					# create root window which can then be hidden
					root = Tkinter.Tk()
					# hide
					root.withdraw()
					tkMessageBox.showerror("%s Integrity check complete" % self.runfolder,"Integrity check failed - please do not use this sequencer and inform the Bioinformatics team immediately" )


	def open_window(self):
		"""
		This function uses TKinter to create a window which remains until a process has finished.
		This process is complete when the run has finished and checksums have been calculated.
		The window closes and is replaced by the info or error in look_for_folder boxes.
		"""
		# create a object for pop up box
		window = Tkinter.Tk()
		# set some properties of the message box
		# message box size
		window.minsize(width=666,height=66)
		# message box title
		window.title("%s - Integrity check not complete - please wait" % self.runfolder)
		# create a label for inside the message box
		label = Tkinter.Label(window, text = "Procesing %s\nPlease don't use this sequencer or close this window until a message box stating \"Integrity check passed\" is displayed"  % self.runfolder)
		# display the label in the window
		label.pack()
		# using threading run the function run_has_finished which closes when the checksums have been generated
		thread = threading.Thread(target = self.run_has_finished)
		# start parallel computation
		thread.start()
		# montior this thread
		while thread.is_alive():
			# update the window
			window.update()
			time.sleep(5)
		#close this window then all checksums are present.
		window.destroy()


	def run_has_finished(self):
		"""
		This function looks at the runfolder, assesses if the run has finished and the data transferred.
		If required the checksums are generated, or if not the script waits until the checksums have been generated (by the demultiplexing script).
		"""
		# build path to the runfolder
		self.sequencer_runfolder = os.path.join(self.sequencer_temp_folder, self.runfolder)
		# build paths on the workstation
		self.workstation_runfolder = os.path.join(self.mapped_workstation_folder, self.runfolder)
		#flag to denote run and data transfer has finished
		finished = False
		# while variable finished is false
		while not finished:
			# check the run has finished and transferred (presence of RTA_complete in the runfolder and on workstation)
			if self.RTA_complete in os.listdir(self.sequencer_runfolder) and self.RTA_complete in os.listdir(self.workstation_runfolder):
					print "no min wait = %s" % self.no_min_wait
					# if it's a testing run print a message
					if self.debug:
						print "debug mode - skipping integrity_check_first_wait"
					elif self.no_min_wait:
						print "no-min-wait - skipping integrity_check_first_wait"
					else:
						# wait the number of hours defined in config file to ensure all file transfers are done
						time.sleep(config.integrity_check_first_wait * 3600)

					# call function which triggers the checksum calculations
					self.prepare_checksum_calculations()
					# now all checksums are done change flag to true so the loop finishes and the window is closed
					finished = True

			# if run has not finished
			else:
				# if a testing run, wait 20 seconds and print a message
				if self.debug:
					print "waiting 20 seconds for sequencing and data transfer to finish"
					time.sleep(20)
				# if not testing wait longer
				else:
					# wait 10 minutes
					time.sleep(600)
		if self.debug:
			print "checksums done"


	def prepare_checksum_calculations(self):
		"""
		The checksums are calculated by this script.
		This function checks the runfolder has not already been checksummed, marks the folder as being checksummed and then calls the function to generate the checksums.
		"""
		if self.debug:
			if self.verbose:
				print "in prepare_checksum_calculations"

		# create name for file to denote checksum in progress
		checksum_in_progress_file = self.runfolder+".txt"
		# check integrity check has not already been calculated, or isn't currently being calculated and it isn't a testing run.
		if not self.debug and self.output_file not in os.listdir(self.workstation_runfolder) and checksum_in_progress_file not in os.listdir(self.checksum_in_progress):
			# create a file to denote checksum in progress
			with open(os.path.join(self.checksum_in_progress,checksum_in_progress_file),'w') as checksum_in_progress_file_path:
				# create a timestamp
				now=datetime.datetime.now()
				# convert timestamp to string and write to file.
				checksum_in_progress_file_path.write(str(now))

			# call function to generate checksum for workstation and sequencer runfolders
			self.run_integrity_check()
		# if a test run print statement to explain stopping
		elif self.debug:
			print "checksums already generated but as testing continuing anyway"
				# create a file to denote checksum in progress
			with open(os.path.join(self.checksum_in_progress,checksum_in_progress_file),'w') as checksum_in_progress_file_path:
				# create a timestamp
				now=datetime.datetime.now()
				# convert timestamp to string and write to file.
				checksum_in_progress_file_path.write(str(now))

			# call function to generate checksum for workstation and sequencer runfolders
			self.run_integrity_check()


	def run_integrity_check(self):
		"""
		This function calculates the checksums.
		If the checksums do not match it repeats the test until it passes or until the maximum number of attempts is reached
		The novaseq and nextseq have different approaches.
		The novaseq temp folder is quite different to the nextseq so the checksum is done on a sub folder by subfolder basis.
		The nextseq compares the entire folder, but excludes specific files which are not copied from temp to output.
		The checksums are written to a file on the workstation for the demultiplexing script to read from.
		"""

		print "starting integrity checking"
		# set a count for max number of attempts at checksum (one test per hour)
		count = 0

		# while the integrity test is failing and not exceeded the max number of attempts
		while not self.checksum_match and count < config.max_number_of_attempts:
			# novaseq and nextseq require different checksum calculations
			if config.nextseq:
				# calculate the md5 checksum for each runfolder, using the to_exclude list
				self.checksum_results["workstation_checksum"] = dirhash(self.workstation_runfolder, 'md5', excluded_files = config.exclude) 
				self.checksum_results["sequencer_checksum"] = dirhash(self.sequencer_runfolder, 'md5', excluded_files = config.exclude)

				# if testing print checksums
				if self.debug:
					print "workstation checksum = " + self.checksum_results["workstation_checksum"]
					print "sequencer checksum = " + self.checksum_results["sequencer_checksum"]

				# see if the checksums match
				if self.checksum_results["workstation_checksum"] == self.checksum_results["sequencer_checksum"]:
					# if they do set self.checksum_match to exit the while loop
					self.checksum_match = True
					# increase count
					count += 1

			if config.novaseq:
				self.checksum_results = {"workstation":{},"sequencer":{}}
				# run integrity check for one sub folder at a time
				for directory in config.include:
					print "novaseq", directory
					# calculate the md5 checksum
					self.checksum_results["workstation"][directory] = dirhash(os.path.join(self.workstation_runfolder,directory), 'md5') 
					self.checksum_results["sequencer"][directory] = dirhash(os.path.join(self.sequencer_runfolder,directory), 'md5')
				print self.checksum_results

				# for the sub folder tested - check each match and count number of successful matches
				matches = 0
				for directory in config.include:
					if self.checksum_results["workstation"][directory] == self.checksum_results["sequencer"][directory]:
						matches +=1
				# if number of matching directories == number of directories tested integrity check has passed.
				if matches == len(config.include):
					# if they do set self.checksum_match to exit the while loop
					self.checksum_match = True
					# increase count
					count += 1

			# if checksums fail
			if not self.checksum_match:
				# increase count
				count += 1
				# if testing skip the wait
				if self.debug:
					print "CHECKSUM FAIL\nmoving files back into workstation runfolder. Integrity test will be repeated shortly..."
					# move files back into folder to make integrity test pass
					if config.nextseq:
						temp_dir_path=os.path.join(self.mapped_drive,"testing_data","workstation","run100_temp")
						file_to_move=os.listdir(temp_dir_path)[0]
						if self.verbose:
							print "moving %s to %s" % (os.path.join(temp_dir_path,file_to_move),os.path.join(self.mapped_drive,"testing_data","workstation","run100",file_to_move))
						os.rename(os.path.join(temp_dir_path,file_to_move),os.path.join(self.mapped_drive,"testing_data","workstation","run100",file_to_move))
					elif config.novaseq:
						# move files back into folder to make integrity test pass
						for dir in config.include:
							file_to_move=os.listdir(os.path.join(self.mapped_drive,"testing_data","workstation",dir+"_temp"))[0]
							if self.verbose:
								print "moving %s to %s" % (os.path.join(self.mapped_drive,"testing_data","workstation",dir+"_temp", file_to_move), os.path.join(self.mapped_drive,"testing_data","workstation","run100",dir,file_to_move))
							os.rename(os.path.join(self.mapped_drive,"testing_data","workstation",dir+"_temp", file_to_move),os.path.join(self.mapped_drive,"testing_data","workstation","run100",dir,file_to_move))
					time.sleep(10)
					count = config.max_number_of_attempts - 1
				else:
					# wait the number of hours defined in config file
					time.sleep(config.integrity_check_repeat_wait * 3600)

		# report if integrity test has passed or failed after max number of tries
		# write the checksums to the output file (on workstation)
		with open(os.path.join(self.workstation_runfolder, self.output_file), 'w') as outputfile:
			if not self.checksum_match:
				# record that it failed, with the number of hours
				outputfile.write("Checksums do not match after " + str(config.max_number_of_attempts) + " hours\n")
			else:
				# record that it passed with the number of hours it took
				outputfile.write(config.checksum_match +" after "+ str(count) + " hours\n")

			if config.nextseq:
				# record the checksums
				outputfile.write("workstation checksum (" + self.workstation_runfolder + ")=" + self.checksum_results["workstation_checksum"] + "\n")
				outputfile.write("sequencer checksum (" + self.sequencer_runfolder + ")=" + self.checksum_results["sequencer_checksum"] + "\n")
			if config.novaseq:
				for directory in config.include:
					# record the checksums
					outputfile.write("workstation checksum (" + self.workstation_runfolder + "/" + directory +")=" + self.checksum_results["workstation"][directory] + "\n")
					outputfile.write("sequencer checksum (" + self.sequencer_runfolder + "/" + directory + ")=" + self.checksum_results["sequencer"][directory] + "\n")
			# if failing integrity check, call function to identify any files which differ between output and temp
			if not self.checksum_match:
				self.identify_missing_files()

	def identify_missing_files(self):
		"""
		Loop through runfolder, or subfolders to identify where there are files on the sequencer that are not on the workstation.
		Then repeat in other direction - looking for any files on workstation that aren't on the sequencer
		"""
		#create output file
		with open(os.path.join(self.workstation_runfolder, config.missing_files_output), 'w') as outputfile:
			if config.nextseq:
				# set flag so header only reported first time
				workstation_missing = False
				# loop through the tempfolder
				for root, subfolder, files in os.walk(os.path.join(self.sequencer_temp_folder, self.runfolder)):
					# for each file in the list of files in that folder
					for file in files:
						# set the path of each file
						path = os.path.join(root,file)
						# create the equivelant path on the workstation
						ws_path = path.replace(self.sequencer_temp_folder,self.mapped_workstation_folder)
						# if the file doesn't exist and it's not a file already identified as not expected on both folders
						if not os.path.isfile(ws_path) and file not in config.exclude:
							# if it's the first missing file we've seen
							if not workstation_missing:
								# print header message
								outputfile.write("Missing from Workstation:\n")
								# set flag so not printed again
								workstation_missing = True
							# print the path to the extra file
							outputfile.write(path)

				# repeat looking for files on workstation that aren't on sequencer
				sequencer_missing = False
				# loop through all files on workstation runfolder
				for root, subfolder, files in os.walk(os.path.join(self.mapped_workstation_folder,self.runfolder)):
					# for each file
					for file in files:
						# set path on workstation
						path = os.path.join(root,file)
						# replace the path on workstation with the expected sequencer path
						sequencer_file_path = path.replace(self.mapped_workstation_folder, self.sequencer_temp_folder)
						# if this file doesn't exist
						if not os.path.isfile(sequencer_file_path) and file not in config.exclude:
							# check if header not already printed
							if not sequencer_missing:
								# print header
								outputfile.write("Missing from Sequencer:\n")
								# set flag so not printed again
								sequencer_missing = True
							# print the path to the extra file
							outputfile.write(path)
			# on Novaseq repeat for the relevant subfolders
			if config.novaseq:
				for folder in config.include:
					# set flag so header only reported first time
					workstation_missing = False
					# loop through the tempfolder
					for root, subfolder, files in os.walk(os.path.join(self.sequencer_temp_folder, self.runfolder, folder)):
						# for each file in the list of files in that folder
						for file in files:
							# set the path of each file
							path = os.path.join(root,file)
							# create the equivelant path on the workstation
							ws_path = path.replace(self.sequencer_temp_folder,self.mapped_workstation_folder)
							# if the file doesn't exist and it's not a file already identified as not expected on both folders
							if not os.path.isfile(ws_path) and file not in config.exclude:
								# if it's the first missing file we've seen
								if not workstation_missing:
									# print header message
									outputfile.write("Missing from Workstation\n")
									# set flag so not printed again
									workstation_missing = True
								# print the path to the extra file
								outputfile.write(path)
								
					# repeat looking for files on workstation that aren't on sequencer
					sequencer_missing = False
					# loop through all files on workstation runfolder
					for root, subfolder, files in os.walk(os.path.join(self.mapped_workstation_folder,self.runfolder, folder)):
						# for each file
						for file in files:
							# set path on workstation
							path = os.path.join(root,file)
							# replace the path on workstation with the expected sequencer path
							sequencer_file_path = path.replace(self.mapped_workstation_folder, self.sequencer_temp_folder)
							# if this file doesn't exist
							if not os.path.isfile(sequencer_file_path) and file not in config.exclude:
								# check if header not already printed
								if not sequencer_missing:
									# print header
									outputfile.write("Missing from Sequencer:\n")
									# set flag so not printed again
									sequencer_missing = True
								# print the path to the extra file
								outputfile.write(path)


def main():
	md5=Sequencer_Integrity_Check()
	# Define arguments.
	parser = argparse.ArgumentParser()
	# add debug argument which is set to true if argument given.
	parser.add_argument('--debug', action='store_true', help="Turn debug mode on.")
	parser.add_argument('--verbose', action='store_true', help="print extra when in debug.")
	parser.add_argument('--no_min_wait', action='store_true', help="skips any minimum wait before calculating checksum.")
	md5.no_min_wait = parser.parse_args().no_min_wait
	# parse arguments and set debug variable in class to debug
	md5.debug = parser.parse_args().debug
	md5.verbose = parser.parse_args().verbose
	# set debug paths
	md5.debug_mode()

	# start integrity checking
	md5.look_for_folder()

if __name__ =="__main__":
	main()