#!/usr/bin/python3

import json
import logging
from lxml import etree
from pathlib import Path
import subprocess
import sys
import traceback

import requests

from utilities import utilities as utes


def error_log(filepath=None):
    """Initiates an error log."""
    if sys.platform == "win32":
        if filepath == None:
            logger = '\\Windows\\Temp\\error_log.log'
        else:
            logger = filepath
    else:
        if filepath == None:
            logger = '/tmp/error_log.log'
        else:
            logger = filepath
    logging.basicConfig(filename=logger, level=logging.WARNING,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    return logger

def as_session(api_url, username, password, session=None):
    '''Should probably add this to utilities.py'''
    try:
        session = requests.Session()
        session.headers.update({'Content_Type': 'application/json'})
        response = session.post(api_url + '/users/' + username + '/login',
                     params={"password": password, "expiring": False})
        if response.status_code != 200:
            print(f"Error could not connect: {response.status_code}")
            return
        else:
            session_toke = json.loads(response.text)['session']
            session.headers['X-ArchivesSpace-Session'] = session_toke
    except Exception:
        print(traceback.format_exc())
    print(f'session: {session}')
    return session

class EADUtils():
    def __init__(self, sesh=None):
        self.config_file = utes.get_config(cfg=str('config.yml')
        self.api_url = self.config_file['api_url']
        self.username = self.config_file['api_username']
        self.password = self.config_file['api_password']
        #is this what I want?
        self.dirpath = utes.setdirectory(self.config_file['backup_directory'])
        #this can be changed, the csvdict function will need to be called again
        self.csvfile = utes.opencsvdict(self.config_file['input_csv'])
        self.ead_3_transformation = self.config_file['ead_3_transformation']
        self.ead_3_schema_path = self.config_file['ead_3_schema']
        self.manifest_path = self.config_file['manifest_path']
        self.transformation_errors = utes.openoutfile(self.config_file['transformation_errors'])
        self.validation_errors = utes.openoutfile(self.config_file['validation_errors'])
        self.saxon_path = self.config_file['saxon_path']
        #self.ead_3_transformation = requests.get("https://raw.githubusercontent.com/YaleArchivesSpace/EAD3-to-PDF-UA/master/xslt-to-update-the-ASpace-export/yale.aspace_v2_to_yale_ead3.xsl").text
        self.ead_3_schema = self.prep_schema_for_validation()
        if sesh is None:
            self.sesh = as_session(api_url=self.api_url, username=self.username, password=self.password)
        else:
            self.sesh = sesh

    def log_subprocess_output(self, pipe):
        for line in iter(pipe.readline, b''):
            logging.warning(line)

    def prep_schema_for_validation(self):
        ead_3_schema_doc = etree.parse(self.ead_3_schema_path)
        return etree.XMLSchema(ead_3_schema_doc)

    def export_ead(self, row, ead3=True, get_ead=None):
        '''Exports EAD files using a list of resource IDs as input.

           Parameters:
            row['resource_id']: The ID of the resource
            row['repo_id']: The ID of the repository

           Returns:
            str: A string representation of the EAD response from the ArchivesSpace API.
        '''
        repo_id = row['repo_id']
        resource_id = row['resource_id']
        print(f'Exporting {resource_id}')
        if ead3 == True:
            get_ead = self.sesh.get(f"{self.api_url}/repositories/{repo_id}/resource_descriptions/{resource_id.strip()}.xml?include_unpublished=true&ead3=true", stream=True).text
        elif ead3 == False:
            get_ead = self.sesh.get(f"{self.api_url}/repositories/{repo_id}/resource_descriptions/{resource_id.strip()}.xml?include_unpublished=true", stream=True).text
        print(f'{resource_id} exported. Writing to file.')
        ead_file_path = f"{self.dirpath}/{resource_id}.xml"
        with open(ead_file_path, 'a', encoding='utf-8') as outfile:
            outfile.write(get_ead)
        print(f'{resource_id} written to file: {ead_file_path}')
        return ead_file_path

    def transform_ead_3(self, ead_file_path):
        '''Transforms EAD files using a user-defined XSLT file.'''
        print(f'Transforming file: {ead_file_path}')
        subprocess.run(["java", "-cp", f"{self.saxon_path}", "net.sf.saxon.Transform",
                        f"-s:{ead_file_path}",
                        f"-xsl:{self.ead_3_transformation}",
                        f"-o:{ead_file_path[:-4]}_out.xml"], stdout=self.transformation_errors, stderr=subprocess.STDOUT,
                       encoding='utf-8')
        #if proc.stderr:
         #   self.log_subprocess_output(proc.stderr)
        #this doesn't mean that it was successful...
        print(f'Transformation finished: {ead_file_path}')
        return f"{ead_file_path[:-4]}_out.xml"
        #return open(f"{ead_file_path[:-4]}_out.xml", 'r', encoding='utf-8').read()

    def validate_ead_3(self, ead_file_path):
        print(f'Validating file: {ead_file_path}')
        try:
            #print(type(ead_file_path))
            with open(ead_file_path, 'r', encoding='utf-8') as open_ead:
                doc = etree.parse(open_ead)
                try:
                    self.ead_3_schema.assertValid(doc)
                    #self.validation_errors.write(f'{ead_file_path} is valid')
                    logging.warning(f'\n\n{ead_file_path} is valid')
                except etree.DocumentInvalid as err:
                    #self.validation_errors.write(f'Schema Validation Error: {ead_file_path}')
                    #self.validation_errors.write(traceback.format_exc())
                    #self.validation_errors.write(err.error_log)
                    logging.warning(f'\n\nSchema Validation Error: {ead_file_path}')
                    #logging.exception('Error: ')
                    logging.warning(err.error_log)
                except Exception:
                    #self.validation_errors.write(f'Other validation error: {ead_file_path}')
                    logging.warning(f'\n\nOther validation error: {ead_file_path}')
                    logging.exception('Error: ')
                    #self.validation_errors.write(traceback.format_exc())
        #this finds a problem with the file
        except IOError:
            #self.validation_errors.write(f'Invalid file: {ead_file_path}')
            #self.validation_errors.write(traceback.format_exc())
            logging.warning(f'\n\nInvalid file: {ead_file_path}')
            logging.exception('Error: ')
        #this finds syntax errors in XML
        except etree.XMLSyntaxError as err:
            #self.validation_errors.write(f'XML Syntax Error: {ead_file_path}')
            #self.validation_errors.write(traceback.format_exc())
            #self.validation_errors.write(err.error_log)
            logging.warning(f'\n\nXML Syntax Error: {ead_file_path}')
            logging.warning(err.error_log)
            logging.exception('Error: ')
        except Exception:
            #self.validation_errors.write(f'Other validation error: {ead_file_path}')
            #self.validation_errors.write(traceback.format_exc())
            logging.warning(f'\n\nOther validation error: {ead_file_path}')
            logging.exception('Error: ')
        print(f'Validation complete: {ead_file_path}')


    def export_transform_validate_ead3(self, row):
        '''Runs export, transform, and validate EAD functions using a user-defined schema file.'''
        ead_file_path = self.export_ead(row)
        transformed_ead_path = self.transform_ead_3(ead_file_path)
        validated_ead = self.validate_ead_3(transformed_ead_path)


if __name__ == "__main__":
    error_log()
    ead_utes = EADUtils()
    logging.warning(f'''Starting logging for EAD export.
                        API URL: {ead_utes.api_url}
                        CSV Input: {ead_utes.config_file['input_csv']}
                    ''')
    for row in ead_utes.csvfile:
        #instead of worrying about real time logging could just do a tqdm bar. The only problem is if it aborts somehow
        ead_utes.export_transform_validate_ead3(row)



'''Standalone script for EAD3 transformations.
Include a check of files in the manifest against published resources in AS??
    -This would require an sql query...
    -Also will require a conversion from MD to CSV - or some other extraction of the list of files
    -Also interested in files which haven't been updated in a long time...

Add in some timing
-Don't really want the outfile to stay as they are because if it aborts before it's over they won't write. Need like a logger or something......
    https://stackoverflow.com/questions/1606795/catching-stdout-in-realtime-from-subprocess

-Find a better way of reporting on transformation errors and errors in validation

-If there is a transformation error then the EAD cannot be validated; find a way to check this before it fails because of this

-Need to abstract some of the paths - i.e. to Saxon

-Put some of the file names in the config file - DONE

'''