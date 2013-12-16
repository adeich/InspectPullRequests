import urllib2, json, re, grequests, time, argparse
from collections import namedtuple


def Main(sGitHubUser, sGitHubProject):

	# Create a printer object.
	oSmartPrinter = SmartPrinter()	

	# from the GitHub API, collect a single json object representing all
	# current pull requests.
	jAllPullRequests = GetGitHubPullRequestsJson(sGitHubUser, sGitHubProject, bPrintStatus=True)
	if not jAllPullRequests:
		return

	# For each pull request in the JSON, get the URL of its diff file. The diff file contains the   # data we use to determine if the pull request is interesting.
	try:
		lDiffURLs = [dPullRequest['diff_url'] for dPullRequest in jAllPullRequests]
	except KeyError as error:
		print "Pull Request JSON oddly missing the 'diff_url' key."
		print error
		
	# Download all pull request diff files. 
	lDiffHTTPResponses = GetAllDiffHTTPResponses(lDiffURLs, bPrintStatus=True)

	# Analyze each pull request to see if and why it's interesting.
	for sDiffURL, sDiffResponse in lDiffHTTPResponses:
		tDiffAnalysis = GenerateDiffAnalysis(sDiffResponse, jAllPullRequests, sDiffURL)

		# If it is interesting, add it to the printer object.
		if tDiffAnalysis.bIsInteresting:
			oSmartPrinter.AddInterestingPullRequest(tDiffAnalysis)

	# Generate a formatted report of interesting pull requests; print to stdout.
	oSmartPrinter.PrintReport() 
			






### helper functions, below. ###

# Download json from GitHub, iterating through any resulting pagination.
def GetGitHubPullRequestsJson(sGitHubUser, sGitHubProject, bPrintStatus=False):
	# Relevant API docs at http://developer.github.com/v3/#pagination
	bWeveLoadedAllPullRequests = False	

	lCollectedOutput = []

	# The GitHub api says this number may not exceed 100.
	iDefaultResultsPerPage = 100

	sNextURL = 'https://api.github.com/repos/{}/{}/pulls?per_page={}'.format(
		sGitHubUser, sGitHubProject, iDefaultResultsPerPage)

	if bPrintStatus:
		print "getting json ..."

	fStartTime = time.time()

	while not bWeveLoadedAllPullRequests:
		try:
			oRequest = urllib2.Request(sNextURL)
			oRequest.add_header('Link', None)
			oResponse = urllib2.urlopen(oRequest)

			# Add new json to collected json.
			lCollectedOutput += json.load(oResponse)
			
			# Get the url data for the next page.
			sLinkHeader = oResponse.info().getheader('Link')
			
			# If the link header is empty, we're at the last page.
			if not sLinkHeader:
				break

			# Otherwise, check the link header for 'next' and 'last' links.
			oNextURLRegex = re.compile('<(https:[^>]+)>; rel=\"next\"').search(sLinkHeader)
			oLastURLRegex = re.compile('<(https:[^>]+)>; rel=\"last\"').search(sLinkHeader)

			# If the link header contains a rel="last" link, then we are not at the last
			# page yet.
			if oLastURLRegex:
				sNextURL = oNextURLRegex.group(1)
				print 'next url: ' + sNextURL
			else:
				bWeveLoadedAllPullRequests = True
			
		except urllib2.HTTPError as error:
			print error
			print 'bad URL: {}'.format(sNextURL)
			print 'check that username and project are correct'
			return None	

	fEndTime = time.time()

	if bPrintStatus:
		print 'Success. Loaded {} pull requests in {} seconds.'.format(len(lCollectedOutput), 
			"%.2f" % round(fEndTime - fStartTime, 2))

	return lCollectedOutput


# Get all diff files concurrently, thanks to grequests.
def GetAllDiffHTTPResponses(lDiffURLs, bPrintStatus=False):

	# Construct a generator of unsent Request objects. 	
	oHTTPRequests = (grequests.get(sURL) for sURL in lDiffURLs)

	if bPrintStatus:
		print 'Loading a total of {} diff files ...'.format(len(lDiffURLs))

	# Get api results for all requests.
	fStartTime = time.time()
	lHTTPOutput = grequests.map(oHTTPRequests)
	fEndTime = time.time()	

	if bPrintStatus:
		print 'Success. Loaded diff files in {} seconds.'.format("%.2f" %
			 round(fEndTime - fStartTime, 2))

	return [(sDiffURL, oDiffResponse.content) for sDiffURL, oDiffResponse in 
		zip(lDiffURLs, lHTTPOutput)]


# A template for storing data about each pull request.
DiffAnalysisTuple = namedtuple('DiffAnalysisTuple', 
		['bIsInteresting',
		'sPullID',
		'dInterestingWordsPresent',
		'dInterestingFilesPresent',
		'lReasonsIsNotInteresting',
		'sUser',
		'sTitle',
		'sURL'])


# For a single pull request, reads in the diff file and returns a tuple, describing
# whether the pull request is interesting.
def GenerateDiffAnalysis(sDiffResponse, jAllPullRequests, sDiffURL):
	lInputLines = sDiffResponse.split('\n')

	bHasReasonsToBeInteresting = False
	bAbsolutelyNotInteresting = False
	lReasonsIsNotInteresting = []

	# matches any line beginning with +++ or ---.
	oFileNameRe = re.compile('(^\+\+\+\s|^\-\-\-\s)(.+)')
	# matches any line beginning with a single + or -, but not with +++ or ---.
	oDiffLineRe = re.compile('(^\+(?!\+\+)|^\-(?!\-\-))(.+)')
	
	lFileNamesSet = set()
	lDiffLinesSet = set()

	# Collect the lines in the diff file which either represent the names
	# of files changed, or the changes themselves.
	for sLine in lInputLines:
		if oFileNameRe.search(sLine):
			lFileNamesSet.add(oFileNameRe.search(sLine).group(2))
		elif oDiffLineRe.search(sLine):
			lDiffLinesSet.add(oDiffLineRe.search(sLine).group(2))

	# Check to make sure there are no '/spec/' files in the diff.
	for sFileName in lFileNamesSet:
		if '/spec/' in sFileName:
			bAbsolutelyNotInteresting = True
			lReasonsIsNotInteresting.append("Contains a /spec/ file.")

	lInterestingWords = ['/dev/null',
			'raise',
			'.write',
			'%x',
			'exec']

	lInterestingFileNames = ['Gemfile', '.gemspec']

	# Construct a dict of numbers, where each number will represent the number of 
	# occurrences of the key in the diff file.
	dInterestingWordsPresent = {sWord: 0 for sWord in lInterestingWords}
	dInterestingFilesPresent = {sFile: 0 for sFile in lInterestingFileNames}

	# Note any diff lines which contain interesting words.
	for sLine in lDiffLinesSet:
		for sWord in lInterestingWords:
			if re.compile('(?<!\w){}(?!\w)'.format(sWord)).search(sLine):
				bHasReasonsToBeInteresting = True
				dInterestingWordsPresent[sWord] += 1

	# Note any filename lines which have interesting names.
	for sLine in lFileNamesSet:
		for sFileName in lInterestingFileNames:
			if re.compile('(?<!\w){}(?!\w)'.format(sFileName)).search(sLine):
				bHasReasonsToBeInteresting = True
				dInterestingFilesPresent[sFileName] += 1

	# Finally, look up info about original pull request in the JSON.
	sPullRequestID = re.compile('.+/pull/(\d+)\.diff').search(sDiffURL).group(1)
	sPullRequestUser, sPullRequestTitle = None, None
	for dPullRequest in jAllPullRequests:
		if str(dPullRequest["number"]) == sPullRequestID:
			sPullRequestTitle = dPullRequest['title']
			sPullRequestUser = dPullRequest['user']['login']
			break
		
	return DiffAnalysisTuple(
		bIsInteresting = (not bAbsolutelyNotInteresting) and bHasReasonsToBeInteresting,
		sPullID = sPullRequestID,
		dInterestingWordsPresent = dInterestingWordsPresent,
		dInterestingFilesPresent = dInterestingFilesPresent,
		lReasonsIsNotInteresting = lReasonsIsNotInteresting,
		sTitle = sPullRequestTitle,
		sUser = sPullRequestUser,
		sURL = sDiffURL)
	
	
# Formats and prints reports of interesting pull requests.
class SmartPrinter:

	def __init__(self):
		self.InterestingPullRequests = []
	
	def AddInterestingPullRequest(self, tDiffAnalysis):
		self.InterestingPullRequests.append(tDiffAnalysis)	

	def PrintReport(self):
		print "Found a total of {} interesting pull requests:\n".format(
			len(self.InterestingPullRequests))
		for tPullRequest in self.InterestingPullRequests:
			print 'Pull Request ID: {}'.format(tPullRequest.sPullID)
			print ''

			print '\tDiff URL: {}'.format(tPullRequest.sURL)
			print '\tTitle:   \'{}\''.format(tPullRequest.sTitle)
			print '\tUser:    \'{}\''.format(tPullRequest.sUser)
			print ''
			
			print "\tReasons is interesting:"
			for sWord, iOccurences in tPullRequest.dInterestingWordsPresent.items():
				if iOccurences > 0:
					print '\t\'{}\' occurs on {} line(s)'.format(sWord, iOccurences)
		
			for sFilename, iOccurences in tPullRequest.dInterestingFilesPresent.items(): 
				if iOccurences > 0:
					print '\tthe file \'{}\' appears {} time(s)'.format(sFilename, iOccurences)
			print '\n' 
			

if __name__ == '__main__':

	# Get command line arguments.
	parser = argparse.ArgumentParser(description='Calls the GitHub API and reports on interesting pull requests.')
	parser.add_argument('user', metavar='user', type=str, 
                   help='GitHub username of project owner')
	parser.add_argument('project', metavar='project', type=str,
                   help='GitHub project name')

	args = parser.parse_args()

	Main(args.user, args.project)
