import re                   # regex string finding/replacing
from pathlib import Path    # 
import frontmatter          # remove yaml frontmatter from md files
import urllib.parse         # convert link characters like %
import warnings
import shutil               # used to remove a non-empty directory, copy files
 
# Lookup tables
image_suffixes = ['jpg', 'jpeg', 'gif', 'png', 'bmp']

class DuplicateFileNameInRoot(Exception):
    pass

class MarkdownPage:
    page = None            # Pure markdown code read from src file
    yaml = None             # Yaml is stripped from the src file and saved here
    codeblocks = None       # used to safely store ```codeblock content
    codelines = None        # Used to safely store `codeline` content
    links = None            # Used to recurse to any page linked to by this page

    src_path  = None        # Path() object of src file
    rel_src_path  = None    # Path() object relative to given markdown root folder (src_folder_path)
    src_folder_path = None  # Path() object of given obsidian root folder
    dst_folder_path = None  # Path() object of given markdown output folder
    dst_path = None         # Path() object of destination file

    file_tree = None        # Tree of files that are found in the root folder

    def __init__(self, src_path, src_folder_path, file_tree):
        self.file_tree = file_tree
        self.src_path = src_path
        self.src_folder_path = src_folder_path
        self.rel_src_path = self.src_path.relative_to(src_folder_path)

        self.links = []
        self.codeblocks = []
        self.codelines = []
        
        # Load contents of entrypoint and strip frontmatter yaml.
        page = frontmatter.load(str(src_path))
        self.page = page.content
        self.yaml = page

    def SetDestinationPath(self, dst_folder_path, entrypoint_src_path):
        """Set destination path of the converted file. Both full and relative paths are set."""
        self.dst_folder_path = dst_folder_path

        if entrypoint_src_path == self.src_path:
            self.dst_path = dst_folder_path.joinpath('index.md')
        else:
            self.dst_path = dst_folder_path.joinpath(self.rel_src_path.as_posix())
        self.rel_dst_path = self.dst_path.relative_to(dst_folder_path)

    def StripCodeSections(self):
        """(Temporarily) Remove codeblocks/-lines so that they are not altered in all the conversions. Placeholders are inserted."""
        self.codeblocks = re.findall("^```([\s\S]*?)```$", self.page, re.MULTILINE)
        for i, match in enumerate(self.codeblocks):
            self.page = self.page.replace("```"+match+"```", f'%%%codeblock-placeholder-{i}%%%')
            
        self.codelines = re.findall("`(.*?)`", self.page)
        for i, match in enumerate(self.codelines):
            self.page = self.page.replace("`"+match+"`", f'%%%codeline-placeholder-{i}%%%')
           
    def RestoreCodeSections(self):
        """Undo the action of StripCodeSections."""
        for i, value in enumerate(self.codeblocks):
            self.page = self.page.replace(f'%%%codeblock-placeholder-{i}%%%', f"```{value}```\n")
        for i, value in enumerate(self.codelines):
            self.page = self.page.replace(f'%%%codeline-placeholder-{i}%%%', f"`{value}`")  

    def ConvertObsidianPageToMarkdownPage(self, dst_folder_path, entrypoint_path, include_depth=0):
        """Full subroutine converting the Obsidian Code to proper markdown. Linked files are copied over to the destination folder."""
        # -- Load contents
        self.SetDestinationPath(dst_folder_path, entrypoint_path)

        rel_obsidian_entrypoint_path = entrypoint_path.relative_to(self.src_folder_path)

        # -- Get page depth
        page_folder_depth = self.rel_src_path.as_posix().count('/')

        # -- [1] Replace code blocks with placeholders so they aren't altered
        # They will be restored at the end
        self.StripCodeSections() 

        # -- [2] Add newline between paragraph and lists
        buffer = ''
        prev_is_list_line = False
        for i, line in enumerate(self.page.split('\n')):
            current_is_list_line = False
            clean_line = line.strip()
            if len(clean_line) == 0:
                current_is_list_line = False
            elif clean_line[0] == '-':
                current_is_list_line = True
            if current_is_list_line and (prev_is_list_line == False):
                buffer += '\n'
            buffer += '\n' + line
            prev_is_list_line = current_is_list_line
        self.page = buffer

        # -- [3] Convert Obsidian type img links to proper md image links
        # Further conversion will be done in the block below
        for link in re.findall("(?<=\!\[\[)(.*?)(?=\])", self.page):
            new_link = '![]('+link+')'

            # Obsidian page inclusions use the same tag...
            # Skip if we don't match image suffixes. Inclusions are handled at the end.
            if len(link.split('.')) == 1 or link.split('.')[-1] not in image_suffixes:
                new_link = f'<inclusion href="{link}" />'

            safe_link = re.escape('![['+link+']]')
            self.page = re.sub(safe_link, new_link, self.page)

        # -- [4] Handle local image links (copy them over to output)
        for link in re.findall("(?<=\!\[\]\()(.*)(?=\))", self.page):
            # Only handle local image files (images located in the root folder)
            if urllib.parse.unquote(link).split('/')[-1] not in self.file_tree.keys():
                continue

            # Build relative paths
            src_file_path_str = self.file_tree[urllib.parse.unquote(link).split('/')[-1]]['fullpath']
            relative_path = Path(src_file_path_str).relative_to(self.src_folder_path)
            dst_file_path = self.dst_folder_path.joinpath(relative_path)

            # Create folders if necessary
            dst_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy file over
            shutil.copyfile(src_file_path_str, dst_file_path)

            # Adjust link in page
            file_name = urllib.parse.unquote(link)
            relative_path = relative_path.as_posix()
            relative_path = ('../' * page_folder_depth) + relative_path
            new_link = '![]('+urllib.parse.quote(relative_path)+')'
            safe_link = re.escape('![]('+link+')')
            self.page = re.sub(safe_link, new_link, self.page)

        # -- [5] Change file name in proper markdown links to path
        # And while we are busy, change the path to point to the full relative path
        proper_links = re.findall("(?<=[^\[]\]\().+?(?=\))", self.page)
        for l in proper_links:
            # Get the filename
            file_name = urllib.parse.unquote(l)

            # Determine if file is markdown
            isMd = False
            if file_name[-3:] == '.md':
                isMd = True
            if Path(file_name).suffix == '':
                isMd = True
                file_name += '.md'
    
            if isMd:
                # Add to list to recurse to the link later
                self.links.append(file_name)

            # Don't continue processing for non local files
            if file_name.split('/')[-1] not in self.file_tree.keys():
                continue

            # Determine paths
            filepath = self.file_tree[file_name.split('/')[-1]]['fullpath']
            relative_path_posix = Path(filepath).relative_to(self.src_folder_path).as_posix()
            dst_filepath = self.dst_folder_path.joinpath(relative_path_posix)

            if isMd: 
                if relative_path_posix == rel_obsidian_entrypoint_path.as_posix():   
                    relative_path_posix = 'index.md'

            # Change the link in the markdown to link to the relative path
            relative_path_posix = ('../' * page_folder_depth) + relative_path_posix
            new_link = ']('+relative_path_posix+')'

            safe_link = re.escape(']('+l+')')
            self.page = re.sub(f"(?<![\[\(])({safe_link})", new_link, self.page)

            if isMd == False:
                # Copy file over to new location
                shutil.copyfile(filepath, dst_filepath)

            
        # -- [6] Replace Obsidian links with proper markdown
        # This is any string in between [[ and ]], e.g. [[My Note]]
        md_links = re.findall("(?<=\[\[).+?(?=\])", self.page)
        for l in md_links:
            # A link in Obsidian can have the format 'filename|alias'
            # If a link does not have an alias, the link name will function as the alias.
            parts = l.split('|')
            filename = parts[0].split('/')[-1]
            alias = filename
            if len(parts) > 1:
                alias = parts[1]

            # Split #Chapter
            hashpart = ''
            parts = filename.split('#')
            if len(parts) > 1:
                filename = parts[0]
                hashpart = parts[1]

            isMd = False
            if filename[-3:] == '.md':
                isMd = True
            else:
                # Always assume that Obsidian filenames are links
                # This is the default behavior. Use proper markdown to link to files
                filename += '.md'

            self.links.append(filename)

            # Links can be made in Obsidian without creating the note.
            # When we link to a nonexistant note, link to the not_created.md placeholder instead.
            if filename not in self.file_tree.keys():
                relative_path_posix = '/not_created.md'
            else:
                # Obtain the full path of the file in the directory tree
                # e.g. 'C:\Users\Installer\OneDrive\Obsidian\Notes\Work\Harbor Docs.md'
                full_path = self.file_tree[filename]['fullpath']
                relative_path_posix = Path(full_path).relative_to(self.src_folder_path).as_posix()
                
                if relative_path_posix == rel_obsidian_entrypoint_path.as_posix():    
                    relative_path_posix = 'index.md'

                relative_path_posix = ('../' * page_folder_depth) +  relative_path_posix

            newlink = urllib.parse.quote(relative_path_posix)

            if hashpart != '':
                hashpart = hashpart.replace(' ', '-').lower()
                newlink += f'#{hashpart}'

            # Replace Obsidian link with proper markdown link
            self.page = self.page.replace('[['+l+']]', f"[{alias}]({newlink})")


        # -- [7] Fix newline issue by adding three spaces before any newline
        self.page = self.page.replace("\n", "   \n")

        # -- [8] Insert markdown links for bare http(s) links (those without the [name](link) format).
        # Cannot start with [, (, nor "
        for l in re.findall("(?<![\[\(\"])(http.[^\s]*)", self.page):
            new_md_link = f"[{l}]({l})"
            safe_link = re.escape(l)
            self.page = re.sub(f"(?<![\[\(])({safe_link})", new_md_link, self.page)

        # -- [9] Remove inline tags, like #ThisIsATag
        # Inline tags are # connected to text (so no whitespace nor another #)
        for l in re.findall("(?<!\S)#[^\s#`]+", self.page):
            tag = l.replace('.', '').replace('#', '')
            new_md_str = f"**{tag}**"
            safe_str = re.escape(l)
            self.page = re.sub(safe_str, new_md_str, self.page)

        # -- [10] Add code inclusions
        for l in re.findall(r'^(\<inclusion href="[^"]*" />)', self.page, re.MULTILINE):
            link = l.replace('<inclusion href="', '').replace('" />', '')
            link_lookup = GetObsidianFilePath(link, self.file_tree)

            if link_lookup == False:
                self.page = self.page.replace(l, f"> **obsidian-html error:** Could not find page {link}.")
                continue
            
            self.links.append(link_lookup[1]['fullpath'])

            if include_depth > 3:
                self.page = self.page.replace(l, f"[{link}]({link_lookup[1]['fullpath']}).")
                continue

            incl_page_path = Path(link_lookup[1]['fullpath']).resolve()
            if incl_page_path.exists() == False or incl_page_path.suffix != '.md':
                self.page = self.page.replace(l, f"> **obsidian-html error:** Error including file or not a markdown file {link}.")
                continue
            
            included_page = MarkdownPage(incl_page_path, self.src_folder_path, self.file_tree)
            included_page.ConvertObsidianPageToMarkdownPage(self.dst_folder_path, entrypoint_path, include_depth=include_depth + 1)
            self.page = self.page.replace(l, included_page.page)

        # -- [1] Restore codeblocks/-lines
        self.RestoreCodeSections()

        return self              

class MarkdownLink:
    """Helper class to abstract away a lot of recurring path-testing logic."""
    url = ''
    
    isValid = True
    isExternal = False
    inRoot = False
    suffix = ''

    src_path = None
    rel_src_path = None
    rel_src_path_posix = None
    page_path = None
    root_path = None

    query_delimiter = ''
    query = ''

    def __repr__(self):
        return f"MarkdownLink(\n\turl = \"{self.url}\", \n\tsuffix = '{self.suffix}', \n\tisValid = {self.isValid}, \n\tisExternal = {self.isExternal}, \n\tinRoot = {self.inRoot}, \n\tsrc_path = {self.src_path}, \n\trel_src_path = {self.rel_src_path}, \n\trel_src_path_posix = {self.rel_src_path_posix}, \n\tpage_path = {self.page_path}, \n\troot_path = {self.root_path} \n)"    

    def __init__(self, url, page_path, root_path, relative_path_md = True, url_unquote=False):
        # Set attributes
        self.relative_path_md = relative_path_md    # Whether the markdown interpreter assumes relative path when no / at the beginning of a link
        self.page_path = page_path
        self.root_path = root_path
        self.url = url
        if url_unquote:
            self.url = urllib.parse.unquote(self.url)

        # Split the query part of "link#query" into self.query
        # Self.url will be the "link" part.
        self.SplitQuery()

        # Url cannot be ''
        # If more tests are needed, they can be added here.
        self.TestisValid()

        # Get suffix, and set suffix to .md if no suffix is present
        self.ParseType()

        # Set self.isExternal if the file contains certain character sequences such as ://
        self.TestIsExternal()
        
        # Set src and rel_src paths
        if self.isValid and self.isExternal == False:
            self.ParsePaths()

    def SplitQuery(self):
        url = self.url
        
        if len(url.split('#')) > 1:
            self.url = url.split('#')[0]
            self.query = url.split('#', 1)[1]
            self.query_delimiter = '#'
            return
        if len(url.split('?')) > 1:
            self.url = url.split('?')[0]
            self.query = url.split('?', 1)[1]
            self.query_delimiter = '?'
            return     

    def TestisValid(self):
        if self.url == '':
            self.isValid = False
            return

    def TestIsExternal(self):
        # Test if \\ // S:\ http(s)://
        if '\\\\' in self.url:
            self.isExternal = True
        if '://' in self.url:
            self.isExternal = True
        if ':\\' in self.url:
            self.isExternal = True

    def ParseType(self):                        
        self.suffix = Path(self.url).suffix

        # Convert path/file to path/file.md
        if self.suffix == '':
            self.url += '.md'
            self.suffix = '.md'

    def ParsePaths(self):
        # /path/file.md --> root_path + url
        # path/file.md --> page_path + url
        if self.url[0] == '/':
            self.src_path = self.root_path.joinpath(self.url[1:]).resolve()
        else:
            if self.relative_path_md:
                self.src_path = self.page_path.parent.joinpath(self.url).resolve()
            else:
                self.src_path = self.root_path.joinpath(self.url).resolve()
            
        # Determine if relative to root
        if self.src_path.is_relative_to(self.root_path):
            self.inRoot = True
        else:
            return

        # Determine relative path
        self.rel_src_path = self.src_path.relative_to(self.root_path)
        self.rel_src_path_posix = self.rel_src_path.as_posix()

def GetObsidianFilePath(link, file_tree):
    # Remove possible alias suffix, folder prefix, and add '.md' to get a valid lookup key
    filename = link.split('|')[0].split('/')[-1].split('#')[-1]

    if filename[-3:] != '.md':
        filename += '.md'
        
    # Return tuple
    if filename not in file_tree.keys():
        return (filename, False)

    return (filename, file_tree[filename])
    