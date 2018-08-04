#!/usr/bin/env python3
#
# LanMonitor is a Windows command-line program intended to alert the user when a new connection has been added to their home wifi.
# A list of LAN devices is provided, with the ability to save custom device names, 
# or use default manufacturer names from an API call to a third-party MAC address manufacturer lookup service. 
#
# Process flow:
# parse arguments
# argument options: help, skip naming request, simply do one scan and stdout, ...
#     or argument for the 'name' of device(s) , or all devices, or none, to alert for
#		both for connecting and disconnecting
# fetch_user_id: get identity of the process' device
# ping_all: get list of connected devices by pinging address range of LAN
# get_macs: get MAC addresses for connected devices
# get_client_names: load the stored names of the connected devices
# for unnamed ('unknown') devices, make API call to get device's manufacturer name
#   and ask the user if they want to name any of the devices.
# (unless arg was given to bypass input request)
# then save these updated names to SQLite file
# 
# use https://macvendors.com/api api to get mac ids
#
# todo: bug involving client_list.  When a disconnect happens, an error with the list creates a duplicate list item
#	for a connected device.

import argparse, configparser, subprocess, re, sqlite3, time, datetime, win32api

ask_name_change = False		# for command-line argument determining whether or not to prompt the user for custom naming of devices.
watched_devices = []		# for command-line argument to contain list of ints, of device ID #'s to be alerted with Windows pop-up.

def fetch_user_id():
	"""Return a dict containing the mac and local IP of the user

	"""

	# run ipconfig /all to get local IP and mac address
	# subprocess.run returns instance of class subprocess.CompletedProcess with stdout attribute
	# parse stdout to retrieve IP and mac
	# return a dictionary with name, ip, mac attributes

	ipconfig_output = subprocess.run(["ipconfig", "/all"], universal_newlines=True, stdout=subprocess.PIPE).stdout
	ipconfig_output = ipconfig_output.splitlines()

	mac_pattern = re.compile('\w\w-\w\w-\w\w-\w\w-\w\w-\w\w')  # re.compile saves a regular expression pattern
	ip_pattern = re.compile('\d+\.\d+\.\d+\.\d+')

	def mac_find():
		for line in ipconfig_output:
			if "Physical Address" in line:
				match = mac_pattern.search(line)
				if(match):
					return line[match.start():match.end()]

	def ip_find():
		for line in ipconfig_output:
			if "IPv4 Address" in line:
				match = ip_pattern.search(line)
				if(match):
					return line[match.start():match.end()]

	ip = ip_find()
	mac = mac_find()
	return {"name": "Your Device", "ip": ip, "mac": mac}



def ping_all(x, timeout=350):
	"""Pings the local LAN IPs to find connected devices.

	returns: list of local IP address strings, int count of IP ping attempts, int total time of function

	x -- user's local IP
	timeout -- ping wait time for response, in milliseconds
	"""
	
	ping_count = 0

	start_time = datetime.datetime.now().time().strftime('%H:%M:%S')
		
	ip_range_pattern = re.compile('\d+\.\d+\.\d+\.')  # compile regex pattern for IP string
	match = ip_range_pattern.search(x)
	ip_list = []   		# list of local client IP connections found
	unused_count = 0    # this will count the number of unused IPs in a row. Will break pinging if enough failed pings.

	if match:
		ip_prefix = x[match.start():match.end()] 
	else:
		sys.exit("error, IP not matching in ping_all function")


	for i in range(0, 255):
		# run ping for every ip in range, with -n 1 for one packet, -l 1 for 1 byte packets, w is ms until timeout
		ip_postfix = ip_prefix + str(i)

		# don't ping yourself
		if x == ip_postfix:
			continue  

		args = ['ping', '-w', str(timeout), '-l', '1', '-n', '1', ip_postfix]
		ping_output = subprocess.run(args, universal_newlines=True, shell=True, stdout=subprocess.PIPE).stdout
		ping_count = ping_count + 1

		exists = True

		not_found_messages = ["unreachable", "timed out", "100%% lost"]
		for n in not_found_messages:
			if n in ping_output:
				exists = False
				unused_count = unused_count + 1
				break

		if exists:
			ip_list.append(ip_postfix)
			unused_count = 0

		if unused_count > 3:  		# make this number higher if there are dozens of devices and errors occur
			break


	end_time = datetime.datetime.now().time().strftime('%H:%M:%S')
	total_time = (datetime.datetime.strptime(end_time,'%H:%M:%S') - datetime.datetime.strptime(start_time,'%H:%M:%S'))

	return ip_list, ping_count, total_time


def get_macs(client_list):
	"""Finds the MAC address for each LAN connected device.

	Returns client_list updated with MAC addresses

	client_list -- list of local IPs connected to LAN
	"""

	mac_pattern = re.compile('\w\w-\w\w-\w\w-\w\w-\w\w-\w\w')  # regex pattern for finding mac addresses

	arp_output = subprocess.run(['arp', '-a'], universal_newlines=True, stdout=subprocess.PIPE).stdout
	arp_output = arp_output.splitlines()

	for client in client_list:
		for line in arp_output:
			if (client['ip'] in line) and (client['mac'] == 'unknown'):
				match = mac_pattern.search(line)
				if(match):
					# add MAC to device info
					client['mac'] = line[match.start():match.end()]
					break   # exit scanning of arp output lines for this client IP since MAC has been found.

	return True


def get_client_names(client_list):
	"""Loads previously stored names and unique ID # for each client from sqlite database file.

	Replaces the "name" value for each dict item in the list called clients_list,
	and replaces any -1 placeholder id value with unique SQL primary key.
	
	client_list -- list of dicts, each item representing a connected LAN device. 
		Each dict has a 'name', 'ip', and 'mac'.
	"""

	conn = sqlite3.connect('clients.db')
	c = conn.cursor()

	for client in client_list:
		try:
			c.execute('SELECT name FROM clients WHERE mac=:mac', client)
			if client['name'] == 'unknown':
				client['name'] = c.fetchone()[0]
				# print(client['mac'] + " had a stored name on file: " + client['name'])
		except sqlite3.IntegrityError as e:
			print("FATAL ERROR")
			None


	for client in client_list:
		try:
			c.execute('SELECT id FROM clients WHERE mac=:mac', client)
			if client['id'] == -1:
				#print("assigning client id for " + client['name'] + " ... ")
				client['id'] = c.fetchone()[0]
				#print("assigned client id#" + str(client['id']) + " for " + client['name'] + " ... ")
		except sqlite3.IntegrityError as e:
			print("FATAL ERROR")
			None

	conn.commit()  	# save changes
	conn.close()	# close sql connection to file



def save_client_name(client):
	"""Saves the name of a connected client to file.

	client - dict containing name, ip, mac for a connected LAN device.
	"""

	conn = sqlite3.connect('clients.db')
	c = conn.cursor()

	try:
		c.execute('UPDATE clients SET name = :name WHERE mac = :mac', client)
	except sqlite3.IntegrityError as e:
		None

	conn.commit()  	# save changes
	conn.close()	# close sql connection to file"""



def get_mac_manufacturer_api(client):
	"""Makes API call to get the manufacturer of a device by it's mac address.

	client -- dict containing client values
	"""
	import requests

	time.sleep(1)

	try:
		response = requests.get('http://api.macvendors.com/' + (client['mac']))
		if response.status_code == requests.codes.ok:
			print("API call response requesting manufacturer of MAC #" + client['mac'] + " ... ")
			print("Manufacturer: " + response.text + ".")
			client['name'] = response.text
	except requests.exceptions.RequestException:
		print("API FAILED")
		return

	pass



def add_clients_to_db(clients_list):
	"""Intended to be run once at program start. Add row to database table if not existing for connected LAN device.

	clients_list -- list of dicts, each dict representing a connected client with 'name', 'ip', and 'mac'
	"""

	conn = sqlite3.connect('clients.db')
	c = conn.cursor()
	c.execute('CREATE TABLE IF NOT EXISTS clients (name text, mac text, id integer primary key, UNIQUE(mac))')
	# c.executemany('INSERT INTO clients VALUES (:name, :mac)', clients_list)

	for client in clients_list:
		c.execute('SELECT * FROM clients WHERE mac = :mac', client)
		if c.fetchone() is None:
			print("Inserting client into table:", client['mac'])
			c.execute('INSERT INTO clients (name, mac) VALUES (:name, :mac)', client)

	conn.commit()  	# save changes
	conn.close()	# close sql connection to file"""



def menu(client_list):
	"""menu lists the current connections and prompts the user if they want to change any device names.

	client_list -- list of dicts, each dict containing name, ip, and mac strings.
	"""

	def prompt():
		global ask_name_change
		"""prompt returns True if it should be repeated

		"""

		print("\nThe connected client list on your LAN: \n")
		for i, client in enumerate(client_list):
			print("Device " + str(client['id']) + ": " + client['ip'] + " " + client['mac'] + " " + client['name'])

		print()

		if not ask_name_change:
			return False

		user_input = input("\nTo change the name of a device, input the device #. Or enter 'n': ")

		if user_input == 'n':
			return False
		else:
			selected_client_id = int(user_input)
			matched_id = False

			for c in client_list:
				if c['id'] == selected_client_id:
					selected_client = c
					matched_id = True
					break

			if matched_id == False:
				print("invalid input")
				return True

			input_name = input("Enter new name for device #" \
			 + user_input + " or enter 'api' to download a name: ")

			if input_name == 'api':
				get_mac_manufacturer_api(selected_client)
			else:
				selected_client['name'] = input_name

			print(selected_client['name'] + " is the new name of that device.")
			save_client_name(selected_client)
			return True
		
			if matched_id == False:
				print("Invalid input.")
				return True


	while(prompt()):
		pass

	print("Monitoring LAN for changes... (hit CTRL + C to quit)")


def connections():
	"""connections is called at startup.  It retrieves the LAN connections information.

	Returns user_id dict and client_list list of dicts for each device. 
	"""

	user_id = fetch_user_id()  # get this computer's local IP and Mac address
	# print("Your local IP is " + user_id['ip'] + " and your MAC is " + user_id['mac'] + ".")

	# get list of IPs of all connected clients. This computer's local IP is function argument.
	client_ip_list, ping_count, ping_time = ping_all(user_id["ip"], 600)
	# print("Pinged " + str(ping_count) + " IPs. Duration of function: " + str(ping_time))

	# create list of dicts, each device is a dict with four key value pairs.
	client_list = []
	for c in client_ip_list:
		client_list.append({'ip': c, 'mac': 'unknown', 'name': 'unknown', 'id': -1})

	get_connections_info(client_list)
	return user_id, client_list




def get_connections_info(client_list):
	"""to be called when a client(s) has been added to the LAN current connections list.
	Updates MAC and device name info, if necessary.

	client_list -- list of dicts"""

	get_macs(client_list)						
	add_clients_to_db(client_list)			# add clients to database that aren't already in database
	get_client_names(client_list)			# adds saved names to client_list's device objects

	# download device manufacturers for devices without a name previously saved.
	for client in client_list:
		if client["name"] == 'unknown':
			get_mac_manufacturer_api(client)
			save_client_name(client)



def monitor(id, client_list):
	"""monitor re-checks current connections.

	id -- dict containing ip, name, mac of this user's device
	client_list --- list of dicts containing ip, mac, and name of connected devices.
	"""
	def run_monitor():
		changes_found = False
		latest_connections = ping_all(id['ip'], 1000)[0]
		listed_client_found = False

		# check if each device in connection list is still there
		for d in client_list:
			ip_found = False
			listed_client_found = False
			for ip in latest_connections:
				if d['ip'] == ip:
					ip_found = True
					latest_connections.remove(ip)
					break

			if ip_found == False:
				changes_found = True
				disconnection_notice(d)
				client_list.remove(d)

		# add new connections
		for new_connection in latest_connections:
			changes_found = True
			print("New connection found: " + new_connection)
			client_list.append({'name': 'unknown', 'ip': new_connection, 'mac': 'unknown', 'id': -1})
			get_connections_info(client_list)
			print(client_list[len(client_list) - 1]['name'] + " added.")
			connection_notice(client_list[len(client_list) - 1])

		if changes_found:
			menu(client_list)
		else:
			pass
			#print("no changes found")


	while(True):
		run_monitor()
		time.sleep(5)




def connection_notice(device):
	global ask_name_change
	global watched_devices

	# insert code , some sort of alert 
	current_time = datetime.datetime.now().time().strftime('%H:%M:%S')
	print(device['name'] + " has connected at " + current_time)

	for d in watched_devices:
		if d == device['id']:
			win32api.MessageBox(0, 'Watched device named ' + device['name'] + ' connected.', 'Device #' + str(device['id']) + " named " + device['name'] + " connected.")



def disconnection_notice(device):
	global ask_name_change
	global watched_devices

	# insert code, some sort of alert
	current_time = datetime.datetime.now().time().strftime('%H:%M:%S')
	print(device['name'] + " has disconnected at " + current_time)

	for d in watched_devices:
		if d == device['id']:
			win32api.MessageBox(0, 'Watched device named ' + device['name'] + ' disconnected.', 'Device #' + str(device['id']) + " named " + device['name'] + " disconnected.")
			 


def main():
	global ask_name_change
	global watched_devices

	program_description = "Lan Monitor can alert the user when a new connection has been added to their home wifi.\n" + \
		"Devices on the LAN have their names stored in SQLite file named clients.db in program folder.\n"

	argparser = argparse.ArgumentParser(description=program_description)
	argparser.add_argument('-r', '--rename_on', action='store_true', help='ask user if they want to rename devices')
	argparser.add_argument('-c', '--connections', action='store_true', help='print list of connected devices and exit')
	argparser.add_argument('-m', '--monitor', action='store_true', help='provide id #\'s of devices to track')
	argparser.add_argument('devices', metavar='device ID#', type=int, nargs='*', help='id of devices to track')

	args = argparser.parse_args()

	if args.rename_on:
		ask_name_change = True
	else:
		ask_name_change = False

	if args.monitor:
		print("monitor arg chosen. ids: " + str(args.devices))
		watched_devices = args.devices

	if args.connections:
		client_list = connections()[1]
		print("\nThe connected client list on your LAN: \n")
		for i, client in enumerate(client_list):
			print("Device " + str(client['id']) + ": " + client['ip'] + " " + client['mac'] + " " + client['name'])

	else:
		user_id, client_list = connections()
	
		# ask user for custom naming of devices
		menu(client_list)
		monitor(user_id, client_list)




if __name__ == '__main__':
	main()


