#! /usr/bin/env python

"""
License:
    NASA Open Source Agreement 1.3

Usage:
    build_elevation_band.py --help prints the help message
"""

import os
import sys
import commands
import logging
import glob
import math
import datetime
from argparse import ArgumentParser


import numpy as np
from lxml import objectify as objectify
from osgeo import gdal, osr


from espa import Metadata
from espa import ENVIHeader


SOFTWARE_VERSION = 'ELEVATION_2.3.1'

# Environment variable for the location of the elevation sources
ESPA_ELEVATION_DIR = 'ESPA_ELEVATION_DIR'


class GeoError(Exception):
    """Exception to capture errors from the Geo class"""
    pass


class Geo(object):
    """Provides methods for interfacing with geographic projections"""

    @staticmethod
    def convert_imageXY_to_mapXY(image_x, image_y, transform):
        """Translate image coordinates into map coordinates

        Args:
            image_x <int>: X coordinate value from the image
            image_y <int>: Y coordinate value from the image
            transform <2x3:float>: GDAL Affine transformation matrix
                                   [0] - Map X of upper left corner
                                   [1] - Pixel size in X direction
                                   [2] - Y rotation
                                   [3] - Map Y of upper left corner
                                   [4] - X rotation
                                   [5] - Pixel size in Y direction

        Returns:
            <float>: Map X for image X
            <float>: Map Y for image Y
        """

        map_x = (transform[0] +
                 image_x * transform[1] +
                 image_y * transform[2])
        map_y = (transform[3] +
                 image_x * transform[4] +
                 image_y * transform[5])

        return (map_x, map_y)

    @staticmethod
    def get_proj4_projection_string(img_filename):
        """Determine the proj4 projection parameters for the specified image

        Proj4 projection parameters are extracted from the specified image.

        Args:
            img_filename (str): The image to extract the projection
                                information from.

        Returns:
            proj4 (str): The proj4 projection string for the image.
        """

        data_set = gdal.Open(img_filename)
        if data_set is None:
            raise RuntimeError('GDAL failed to open ({0})'
                               .format(img_filename))

        ds_srs = osr.SpatialReference()
        ds_srs.ImportFromWkt(data_set.GetProjection())

        proj4 = ds_srs.ExportToProj4()

        del ds_srs
        del data_set

        return proj4

    @staticmethod
    def warp(resampling_method=None,
             resolution_x=None,
             resolution_y=None,
             target_srs=None,
             image_extents=None,
             destination_no_data=None,
             output_data_type=None,
             output_format=None,
             source_data=None,
             output_filename=None):
        """Generates a gdalwarp command line and executes it

        Args:
            resampling_method <str>: gdalwarp defined
            resolution_x <float>: Resoultion to make the output
            resolution_y <float>: Resoultion to make the output
            target_srs <str>: Target projection (gdal compliant proj4
                              projection string)
            images_extents <dict>: Contains the min and max subset window
            destination_no_data <float>: No data value for the output
            output_data_type <str>: gdalwarp defined
            output_format <str>: gdalwarp defined
            source_data <str>: Path to the source data
            output_filename <str>: Path to the output filename
        """

        logger = logging.getLogger(__name__)

        # Base Command
        cmd = ['gdalwarp', '-wm', '2048', '-multi', '-overwrite']

        # Add resampling
        if resampling_method is not None:
            cmd.extend(['-r', resampling_method])

        # Add resolution
        if ((resolution_x is not None and resolution_y is None) or
                (resolution_x is None and resolution_y is not None)):
            raise GeoError('Must specify both X and Y resolution for warping')

        if resolution_x is not None and resolution_y is not None:
            cmd.extend(['-tr', str(resolution_x), str(resolution_y)])

        # Add target projection
        if target_srs is not None:
            cmd.extend(['-t_srs', ''.join(['"', target_srs, '"'])])

        # Add image extents
        if image_extents is not None:
            cmd.extend(['-te',
                        str(image_extents['min_x']),
                        str(image_extents['min_y']),
                        str(image_extents['max_x']),
                        str(image_extents['max_y'])])

        # Add no data value to specify for the output
        if destination_no_data is not None:
            cmd.extend(['-dstnodata', str(destination_no_data)])

        # Add output data type
        if output_data_type is not None:
            cmd.extend(['-ot', output_data_type])

        # Add output format
        if output_format is not None:
            cmd.extend(['-of', output_format])

        # Add the source data
        if source_data is None:
            raise GeoError('Must provide source data')

        if type(source_data) is list:
            cmd.extend(source_data)
        else:
            cmd.append(source_data)

        # Add the output filename
        if output_filename is None:
            raise GeoError('Must provide the output filename')

        cmd.append(output_filename)

        # Convert to a string for the execution
        cmd = ' '.join(cmd)

        output = ''
        try:
            logger.info('EXECUTING WARP COMMAND [{0}]'.format(cmd))
            output = execute_cmd(cmd)
        finally:
            if len(output) > 0:
                logger.info(output)


class MathError(Exception):
    """Exception to capture errors from the Math class"""
    pass


class Math(object):
    """Provides methods for mathematical algorithms"""

    @staticmethod
    def point_in_polygon(vertices, x_c, y_c):
        """Determines if a given point is within a closed polygon

        Algorithm:
            Based on W. Randolph Franklin's algorithm:
                http://www.ecse.rpi.edu
                /Homepages/wrf/Research/Short_Notes/pnpoly.html

            See also the Wikipedia page:
                http://eni.wikipedia.org
                /wiki/Point_in_polygon

        Args:
            vertices <list:x,list:y>: Contains a list of X and Y closed
                                      polygon vertices
            x_c <float>: X coordinate to test against the polygon
            y_c <float>: Y coordinate to test against the polygon

        Notes:
            Derived from Landsat IAS code, which is based on above algorithm.
            A closed list is expected.  Where v[N] = v[0]
            The polygon is always expected to be clock-wise segments.
        """

        count = len(vertices)
        if count < 4:
            raise MathError('Insufficient Line Segments')

        # Convert to x and y lists
        (x_v, y_v) = map(list, zip(*vertices))

        if x_v[0] != x_v[count - 1] and y_v[0] != y_v[count - 1]:
            raise MathError('Not A Closed Polygon Vertex List')

        # Start off by saying outside the polygon
        inside_polygon = False

        # Test each segment
        for index in xrange(count - 1):
            if (((x_v[index] > x_c) != (x_v[index + 1] > x_c)) and
                    (y_c < ((y_v[index + 1] - y_v[index]) *
                            (x_c - x_v[index]) /
                            (x_v[index + 1] - x_v[index]) +
                            y_v[index]))):

                inside_polygon = not inside_polygon

        return inside_polygon

    @staticmethod
    def longitude_norm(longitude):
        """Calculates the "canonical longitude" for the longitude value

        Args:
            longitude <float>: Decimal degrees for the longitude

        Returns:
            result <float>: Equivalent longitude value in the range
                            (-180.0, 180.0) degrees
        """

        result = longitude

        while result < -180.0:
            result += 360.0

        while result >= 180.0:
            result -= 360.0

        return result


def execute_cmd(cmd):
    """Execute a command line

    The specified command line is executed and the terminal output is returned
    or an exception is raised.

    Returns:
        output (str): The stdout and/or stderr from the executed command.
    """

    output = ''

    (status, output) = commands.getstatusoutput(cmd)

    if status < 0:
        message = 'Application terminated by signal [{0}]'.format(cmd)
        if len(output) > 0:
            message = ' Stdout/Stderr is: '.join([message, output])
        raise Exception(message)

    if status != 0:
        message = 'Application failed to execute [{0}]'.format(cmd)
        if len(output) > 0:
            message = ' Stdout/Stderr is: '.join([message, output])
        raise Exception(message)

    if os.WEXITSTATUS(status) != 0:
        message = ('Application [{0}] returned error code [{1}]'
                   .format(cmd, os.WEXITSTATUS(status)))
        if len(output) > 0:
            message = ' Stdout/Stderr is: '.join([message, output])
        raise Exception(message)

    return output


class RAMPCoverageError(Exception):
    """Exception to capture RAMP data not covering the input data"""
    pass


class GLSOverWaterError(Exception):
    """Exception to capture when GLS data is over water"""
    pass


class BaseElevation(object):
    """Defines the base class object for elevation generation/processing"""

    def __init__(self, elevation_filename):
        """Class initialization
        Args:
        elevation_filename - allows the user to specify the output filename
                             for the elevation band; if None then the default
                             filename is used
        """
        super(BaseElevation, self).__init__()

        self.xml_filename = None
        self.number_of_lines = None
        self.number_of_samples = None
        self.pixel_units = None

        # Grab what we need from the environment first
        if ESPA_ELEVATION_DIR not in os.environ:
            raise RuntimeError('{0} environment variable not defined'
                               .format(ESPA_ELEVATION_DIR))
        self.espa_elevation_dir = os.environ.get(ESPA_ELEVATION_DIR)

        # Padding to add to the max box (degrees)
        self.maxbox_padding = 0.2

        # Latitude coordinate limits
        self.north_latitude_limit = 90.0
        self.south_latitude_limit = -90.0
        # Longitude coordinate limits
        self.east_longitude_limit = 180.0
        self.west_longitude_limit = -180.0

        # GLS latitude coordinate limits
        self.glsdem_north_limit = 83.0
        self.glsdem_south_limit = -53.0

        # RAMP lat coordinate limits
        # Defines when we start to use RAMP data
        self.ramp_south_limit = -60.0

        # WGS84 GEOID Adjustment Information
        self.wgs84_dir = 'geoid'
        self.wgs84_header_name = 'geoid.hdr'
        self.wgs84_image_name = 'geoid.img'

        self.wgs84_header_path = os.path.join(self.espa_elevation_dir,
                                              self.wgs84_dir,
                                              self.wgs84_header_name)
        self.wgs84_image_path = os.path.join(self.espa_elevation_dir,
                                             self.wgs84_dir,
                                             self.wgs84_image_name)

        # RAMP Information
        self.ramp_dir = 'ramp'
        self.ramp_header_name = 'ramp200dem_wgs_v2.hdr'
        self.ramp_image_name = 'ramp200dem_wgs_v2.img'

        self.ramp_header_path = os.path.join(self.espa_elevation_dir,
                                             self.ramp_dir,
                                             self.ramp_header_name)
        self.ramp_image_path = os.path.join(self.espa_elevation_dir,
                                            self.ramp_dir,
                                            self.ramp_image_name)

        # GLS Information
        self.gls_dir = 'gls'
        self.gls_projection_template = 'gls_projection.prj'

        # GTOPT30 Information
        self.gtopo30_dir = 'gtopo30'
        self.gtopo30_dems_regexp = '[EW]???[NS]??.DEM'
        self.gtopo30_files_regexp = '[EW]???[NS]??.*'
        self.gtopo30_padding = 1.0  # Degrees, since we are in geographic

        # Elevation format and naming. If the output elevation filename was
        # specified then use it otherwise use the default filename.
        self.elevation_format = 'ENVI'
        self.elevation_type_int16 = 'Int16'
        if elevation_filename is None:
            self.elevation_image_name_fmt = '{0}_elevation.img'
            self.elevation_header_name_fmt = '{0}_elevation.hdr'
        else:
            self.elevation_image_name_fmt = elevation_filename
            self.elevation_header_name_fmt = elevation_filename.  \
                                            replace('.img', '.hdr')

        # Landsat uses bi-linear for all elevation warping
        self.elevation_resampling_method = 'bilinear'

        # MOSAIC Filenames
        self.mosaic_header_name = 'espa-mosaic-elevation.hdr'
        self.mosaic_image_name = 'espa-mosaic-elevation.img'

        # GDAL AUX files to remove
        self.gdal_aux_regexp = '*.img.aux.xml'

        # Initialize the following to something bad
        self.bounding_north_latitude = -9999.0
        self.bounding_south_latitude = 9999.0
        self.bounding_east_longitude = -9999.0
        self.bounding_west_longitude = 9999.0

        self.min_x_extent = None
        self.max_y_extent = None
        self.max_x_extent = None
        self.min_y_extent = None
        self.grid_origin = 'undefined'

        self.pixel_resolution_x = None
        self.pixel_resolution_y = None

        self.target_srs = None

        self.elevation_header_name = None
        self.elevation_image_name = None

    def parse_metadata(self):
        """Implement this to parse the metadata file"""
        raise NotImplementedError('Please Implement Me In {0}'
                                  .format(str(type(self))))

    def mosaic_tiles(self, tiles):
        """MOSAIC the specified tiles into one file"""

        '''
        Set the no data value to 0 so we fill-in with sea-level,
        because missing tiles in GLS will be water(ocean)
        NOTE - This is abusing GDAL, which does not correctly
               output ENVI headers.  The header fixing code, should
               be taking care of it.
        '''
        Geo.warp(destination_no_data=0,
                 output_data_type=self.elevation_type_int16,
                 output_format=self.elevation_format,
                 source_data=tiles,
                 output_filename=self.mosaic_image_name)

    def mosaic_cleanup(self):
        """Remove the MOSAIC files"""

        os.unlink(self.mosaic_header_name)
        os.unlink(self.mosaic_image_name)

    def warp_to_source_data(self, source_name):
        """Warp to the source data"""

        image_extents = {'min_x': self.min_x_extent,
                         'min_y': self.min_y_extent,
                         'max_x': self.max_x_extent,
                         'max_y': self.max_y_extent}

        Geo.warp(resampling_method=self.elevation_resampling_method,
                 resolution_x=self.pixel_resolution_x,
                 resolution_y=self.pixel_resolution_y,
                 target_srs=self.target_srs,
                 image_extents=image_extents,
                 output_data_type=self.elevation_type_int16,
                 output_format=self.elevation_format,
                 source_data=source_name,
                 output_filename=self.elevation_image_name)

    def shift_longitude(self, dem_name, shifted_dem_name, offset):
        """Shift the longitude of the DEM data"""

        logger = logging.getLogger(__name__)

        # Set up the base command
        cmd = ['gdal_translate', '-a_ullr']

        # Get the current locations
        dem_src = gdal.Open(dem_name)
        ulx, xres, xskew, uly, yskew, yres = dem_src.GetGeoTransform()

        # Compute the adjusted longitude locations
        lrx = ulx + (dem_src.RasterXSize * xres)
        lry = uly + (dem_src.RasterYSize * yres)
        new_ulx = ulx + offset
        new_lrx = lrx + offset

        # Close the dataset
        dem_src = None

        # Add updated coordinates to the command
        cmd.extend([str(new_ulx), str(uly), str(new_lrx), str(lry)])

        # Add source and destination files to the command
        cmd.extend([dem_name, shifted_dem_name])

        # Convert to a string for the execution
        cmd = ' '.join(cmd)

        output = ''
        try:
            logger.info('EXECUTING TRANSLATE COMMAND [{0}]'.format(cmd))
            output = execute_cmd(cmd)
        finally:
            if len(output) > 0:
                logger.info(output)

    def _verify_ramp_overlap(self,
                             ramp_lines,
                             ramp_samples,
                             ramp_transform,
                             map_ul_x, map_ul_y,
                             map_ur_x, map_ur_y,
                             map_lr_x, map_lr_y,
                             map_ll_x, map_ll_y,
                             map_center_x, map_center_y):
        """Verify that the input data is covered by the RAMP DEM

        Args:
            ramp_lines <int>:
            ramp_samples <int>:
            ramp_transform <2x3:float>: GDAL Affine transformation matrix
                                        [0] - Map X of upper left corner
                                        [1] - Pixel size in X direction
                                        [2] - Y rotation
                                        [3] - Map Y of upper left corner
                                        [4] - X rotation
                                        [5] - Pixel size in Y direction
            map_ul_x <float>: Upper left image X in projection coordinates
            map_ul_y <float>: Upper left iMage Y in projection coordinates
            map_ur_x <float>: Upper right image X in projection coordinates
            map_ur_y <float>: Upper right image Y in projection coordinates
            map_lr_x <float>: Lower right image X in projection coordinates
            map_lr_y <float>: Lower right image Y in projection coordinates
            map_ll_x <float>: Lower left image X in projection coordinates
            map_ll_y <float>: Lower left image Y in projection coordinates
            map_center_x <float>: Center image X in projection coordinates
            map_center_y <float>: Center image Y in projection coordinates

        Returns:
            Generates RAMPCoverageError exception if image is not contained
            enough by the RAMP DEM.
        """

        logger = logging.getLogger(__name__)

        # Setup the X and Y polygons values
        vertices = list()

        # UL (X, Y)
        (ramp_x, ramp_y) = Geo.convert_imageXY_to_mapXY(0.0, 0.0,
                                                        ramp_transform)
        vertices.append([ramp_x, ramp_y])

        # UR (X, Y)
        (ramp_x, ramp_y) = Geo.convert_imageXY_to_mapXY(ramp_samples-1, 0.0,
                                                        ramp_transform)
        vertices.append([ramp_x, ramp_y])

        # LR (X, Y)
        (ramp_x, ramp_y) = Geo.convert_imageXY_to_mapXY(ramp_samples-1,
                                                        ramp_lines-1,
                                                        ramp_transform)
        vertices.append([ramp_x, ramp_y])

        # LL (X, Y)
        (ramp_x, ramp_y) = Geo.convert_imageXY_to_mapXY(0.0, ramp_lines-1,
                                                        ramp_transform)
        vertices.append([ramp_x, ramp_y])

        # Close the polygon
        vertices.append(vertices[0])

        logger.debug('Vertices: {0}'.format(str(vertices)))

        # No longer needed
        del ramp_transform

        # Determine how many points are within the RAMP DEM and error
        # accordingly
        points_in_polygon = 0
        if Math.point_in_polygon(vertices, map_ul_x, map_ul_y):
            points_in_polygon += 1

        if Math.point_in_polygon(vertices, map_ur_x, map_ur_y):
            points_in_polygon += 1

        if Math.point_in_polygon(vertices, map_lr_x, map_lr_y):
            points_in_polygon += 1

        if Math.point_in_polygon(vertices, map_ll_x, map_ll_y):
            points_in_polygon += 1

        if Math.point_in_polygon(vertices, map_center_x, map_center_y):
            points_in_polygon += 1

        if points_in_polygon < 3:
            raise RAMPCoverageError('Insufficient overlap:'
                                    ' Only found {0} points within'
                                    ' data when at least 3 are'
                                    ' required'.format(points_in_polygon))

    def generate_using_ramp(self):
        """Retrieve the RAMP DEM data"""

        logger = logging.getLogger(__name__)

        # Link the RAMP data to the current directory
        if not os.path.exists(self.ramp_image_name):
            # Should only need to test for one of them
            os.symlink(self.ramp_header_path, self.ramp_header_name)
            os.symlink(self.ramp_image_path, self.ramp_image_name)

        # Open the RAMP dataset
        ramp_ds = gdal.Open(self.ramp_image_name)

        # Create the RAMP SRS
        ramp_srs = osr.SpatialReference()
        ramp_srs.ImportFromWkt(ramp_ds.GetProjection())
        logger.debug('RAMP WKT: {0}'.format(ramp_ds.GetProjection()))

        # Create the Geographic SRS
        latlon_srs = ramp_srs.CloneGeogCS()

        # Create the coordinate transformation
        ll_to_ramp = osr.CoordinateTransformation(latlon_srs, ramp_srs)

        # Find the center of the max box
        center_latitude = ((self.bounding_north_latitude +
                            self.bounding_south_latitude) / 2.0)
        center_longitude = ((self.bounding_east_longitude +
                             self.bounding_west_longitude) / 2.0)

        # Find the max box and center in map coordinates
        (map_ul_x, map_ul_y, height) = (
            ll_to_ramp.TransformPoint(self.bounding_west_longitude,
                                      self.bounding_north_latitude))
        (map_ur_x, map_ur_y, height) = (
            ll_to_ramp.TransformPoint(self.bounding_east_longitude,
                                      self.bounding_north_latitude))
        (map_lr_x, map_lr_y, height) = (
            ll_to_ramp.TransformPoint(self.bounding_east_longitude,
                                      self.bounding_south_latitude))
        (map_ll_x, map_ll_y, height) = (
            ll_to_ramp.TransformPoint(self.bounding_west_longitude,
                                      self.bounding_south_latitude))
        (map_center_x, map_center_y, height) = (
            ll_to_ramp.TransformPoint(center_longitude, center_latitude))
        logger.debug('map_ul_x, map_ul_y: {0}, {1}'
                     .format(map_ul_x, map_ul_y))
        logger.debug('map_ur_x, map_ur_y: {0}, {1}'
                     .format(map_ur_x, map_ur_y))
        logger.debug('map_lr_x, map_lr_y: {0}, {1}'
                     .format(map_lr_x, map_lr_y))
        logger.debug('map_ll_x, map_ll_y: {0}, {1}'
                     .format(map_ll_x, map_ll_y))
        logger.debug('map_center_x, map_center_y: {0}, {1}'
                     .format(map_center_x, map_center_y))

        # Get the RAMP transform
        ramp_transform = ramp_ds.GetGeoTransform()

        # Get the lines and samples from the RAMP band data
        ramp_band = ramp_ds.GetRasterBand(1)
        logger.debug('Lines, Samples: {0}, {1}'
                     .format(ramp_band.YSize, ramp_band.XSize))

        # This causes an exception if they do not overlap
        self._verify_ramp_overlap(ramp_band.YSize, ramp_band.XSize,
                                  ramp_transform,
                                  map_ul_x, map_ul_y,
                                  map_ur_x, map_ur_y,
                                  map_lr_x, map_lr_y,
                                  map_ll_x, map_ll_y,
                                  map_center_x, map_center_y)

        # Cleanup memory before warping
        del ll_to_ramp
        del latlon_srs
        del ramp_transform
        del ramp_band
        del ramp_srs
        del ramp_ds

        # Warp to the source data
        self.warp_to_source_data(self.ramp_image_name)

        # Remove the symlink to the RAMP DEM
        os.unlink(self.ramp_header_name)
        os.unlink(self.ramp_image_name)

    def get_gtopo30_tile_list(self):
        """Generate the list of GTOPO30 DEM tiles"""

        logger = logging.getLogger(__name__)

        # GTOPO30 tile information
        NORTH_LON_LOCATIONS = np.array([-180.0, -140.0, -100.0, -60.0, -20.0,
                                        20.0, 60.0, 100.0, 140.0])

        SOUTH_LON_LOCATIONS = np.array([-180.0, -120.0, -60.0,
                                        0.0, 60.0, 120.0])

        LAT_LOCATIONS = np.array([90.0, 40.0, -10.0, -60.0])

        GTOPO30_TILE_SET_CUTOFF_LATITUDE = -60.0

        '''
        The tiles do not necessarily go all the way to the boundary.  For
        example, the w100n90 tile only goes to -99.995833333334 longitude.
        Thus, if our UL longitude falls between -99.995833333334 and -100.0
        then we will need to use w140n90 to get the far left edge.  To
        account for this we'll artificially pad the East and West boundaries
        by 1 degree.

        Note: this does not seem to cause problems on the North and South
        borders, so we will no worry about them.
        '''
        ul_lon = Math.longitude_norm(self.bounding_west_longitude -
                                     self.gtopo30_padding)
        lr_lon = Math.longitude_norm(self.bounding_east_longitude +
                                     self.gtopo30_padding)
        logger.debug('ul_lon = {0}'.format(ul_lon))
        logger.debug('lr_lon = {0}'.format(lr_lon))

        '''
        There is a condition which could cause problems on the North and South
        boundaries as well.  This is if a scene comes very near the edge, but
        does not quite get there.  It could be that adding 1.5 to nrows before
        taking the ceiling (see calculation of nrows in get_gtopo30_data.c)
        causes the nrows to be large enough that we need data from the tile to
        the South, even though the scene stopped just before that tile.  To
        address this we will grow North and South by 1 degree as we did in the
        East and West directions above.  Note, the same problem can occur in
        the East and West directions, but was already addressed when adding
        one to the longitudes above.
        '''
        ul_lat = min((self.bounding_north_latitude + self.gtopo30_padding),
                     self.north_latitude_limit)
        lr_lat = max((self.bounding_south_latitude - self.gtopo30_padding),
                     self.south_latitude_limit)
        logger.debug('ul_lat = {0}'.format(ul_lat))
        logger.debug('lr_lat = {0}'.format(lr_lat))

        # Determine the unique latitudes where the input data resides
        lat_list = list(set([min(LAT_LOCATIONS[np.where(ul_lat < LAT_LOCATIONS)]),
                             min(LAT_LOCATIONS[np.where(lr_lat < LAT_LOCATIONS)])]))
        logger.debug('lat_list = {0}'.format(lat_list))

        tile_list = list()
        # Determine the unique longitudes where the input data resides
        for lat in lat_list:
            lon_list = list()
            if lat > GTOPO30_TILE_SET_CUTOFF_LATITUDE:
                lon_list.append(
                    max(NORTH_LON_LOCATIONS[
                        np.where(ul_lon > NORTH_LON_LOCATIONS)]))
                lon_list.append(
                    max(NORTH_LON_LOCATIONS[
                        np.where(lr_lon > NORTH_LON_LOCATIONS)]))
            else:
                lon_list.append(
                    max(SOUTH_LON_LOCATIONS[
                        np.where(ul_lon > SOUTH_LON_LOCATIONS)]))
                lon_list.append(
                    max(SOUTH_LON_LOCATIONS[
                        np.where(lr_lon > SOUTH_LON_LOCATIONS)]))
            lon_list = list(set(lon_list))
            logger.debug('lon_list = {0}'.format(lon_list))

            n_s = 'n'
            if lat < 0:
                n_s = 's'

            for lon in lon_list:
                e_w = 'e'
                if lon <= 0:
                    e_w = 'w'

                # Already know if north/south, east/west so we just need
                # the positive value for the filename
                abs_lat = abs(lat)
                abs_lon = abs(lon)

                tile_list.append('{0}{1:03}{2}{3:02}'
                                 .format(e_w, int(abs_lon), n_s, int(abs_lat)))

        return tile_list

    def get_gtopo30_dems(self):
        """Retrieves the GTOPO30 DEM archives and extracts them"""

        logger = logging.getLogger(__name__)

        elevation_dir = os.path.join(self.espa_elevation_dir, self.gtopo30_dir)

        # Determine the GTOPO30 tiles
        tile_list = self.get_gtopo30_tile_list()
        logger.info('GTOPO30 Tile Names: {0}'.format(', '.join(tile_list)))

        for tile in tile_list:
            tile_arch = '{0}.tar.gz'.format(tile)
            tile_path = os.path.join(elevation_dir, tile_arch)

            output = ''
            try:
                cmd = 'cp {0} .'.format(tile_path)
                output = execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    logger.info(output)

            output = ''
            try:
                cmd = 'tar -xvf {0}'.format(tile_arch)
                output = execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    logger.info(output)

            os.unlink(tile_arch)

        # Grab the tile DEM filenames from the extracted archives
        tile_elevation_list = glob.glob(self.gtopo30_dems_regexp)
        logger.info('GTOPO30 DEM Files: {0}'
                    .format(', '.join(tile_elevation_list)))

        return tile_elevation_list

    def generate_using_gtopo30(self):
        """Generate the DEM using GTOPO30 data"""

        logger = logging.getLogger(__name__)

        # Retrieve the GTOPO30 tiles
        tile_elevation_list = self.get_gtopo30_dems()

        # If the image crosses the 180 meridian, shift the west tile
        # longitudes to use the 0..360 range so the mosaic is not confused
        start_longitude = int(math.floor(self.bounding_west_longitude))
        end_longitude = int(math.floor(self.bounding_east_longitude))

        if start_longitude > 0 and end_longitude < 0:

            for tile in tile_elevation_list:
                hemisphere = tile[:1]
                if hemisphere == "W":

                    # Name the shifted output file
                    shifted_tile = tile + '_shifted'

                    # Shift the longitude values
                    self.shift_longitude(tile, shifted_tile, 360)

                    # Copy destination file back to source file
                    output = ''
                    try:
                        cmd = 'cp {0} {1}'.format(shifted_tile, tile)
                        output = execute_cmd(cmd)
                    finally:
                        if len(output) > 0:
                            logger.info(output)

        # MOSAIC the tiles together
        self.mosaic_tiles(tile_elevation_list)

        # Warp to the source data
        self.warp_to_source_data(self.mosaic_image_name)

        # Cleanup intermediate data
        self.mosaic_cleanup()

        remove_list = glob.glob(self.gtopo30_files_regexp)
        for file_name in remove_list:
            os.unlink(file_name)

    def generate_using_gls(self):
        """Retrieve the GLS DEM data"""

        logger = logging.getLogger(__name__)

        elevation_dir = os.path.join(self.espa_elevation_dir, self.gls_dir)

        '''
        GLS tiles are named with a format like n47w118 where the lat/long
        in the file name are the lower-left corner of the tile.  Each tile
        covers a 1-degree by 1-degree area. */
        '''
        start_latitude = int(math.floor(self.bounding_north_latitude))
        end_latitude = int(math.floor(self.bounding_south_latitude))
        start_longitude = int(math.floor(self.bounding_west_longitude))
        end_longitude = int(math.floor(self.bounding_east_longitude))
        logger.debug('Start Latitude: {0}'.format(start_latitude))
        logger.debug('End Latitude: {0}'.format(end_latitude))
        logger.debug('Start Longitude: {0}'.format(start_longitude))
        logger.debug('End Longitude: {0}'.format(end_longitude))

        tile_list = list()

        # Build the list of longitudes to process, taking into account that
        # there could be a 180 meridian crossing.
        longitude_list = list()
        if start_longitude > 0 and end_longitude < 0:
            # The start and end longitudes are on different sides of the
            # antimeridian.  Note: there are no e180 GLS tiles, only some
            # w180 tiles, so don't look for e180.
            for lon in xrange(start_longitude, 179 + 1):
                longitude_list.append(lon)
            for lon in xrange(-180, end_longitude + 1):
                longitude_list.append(lon)
        else:
            for lon in xrange(start_longitude, end_longitude + 1):
                longitude_list.append(lon)

        for lat in xrange(end_latitude, start_latitude + 1):
            logger.debug('Latitude: {0}'.format(lat))
            n_s = 'n'
            if lat < 0:
                n_s = 's'

            for lon in longitude_list:
                logger.debug('Longitude: {0}'.format(lon))

                e_w = 'e'
                if lon < 0:
                    e_w = 'w'

                # Already know if north/south, east/west so we just need
                # the positive value for the filename
                abs_lat = abs(lat)
                abs_lon = abs(lon)

                tile_list.append('{0}{1:02}{2}{3:03}'
                                 .format(n_s, abs_lat, e_w, abs_lon))

        tile_count = len(tile_list)
        if tile_count == 0:
            raise RuntimeError('Unable to determine tiles while retrieving'
                               ' required GLS DEM tile list')

        '''
        Generate lists of the BIL, HDR, and PRJ filenames as well as
        determining any missing tiles
        '''
        missing_count = 0
        bil_list = list()
        hdr_list = list()
        prj_list = list()
        prj_path = os.path.join(elevation_dir, self.gls_projection_template)
        logger.debug('PRJ Path: {0}'.format(prj_path))
        for tile in tile_list:
            bil_name = '{0}.bil'.format(tile)
            hdr_name = '{0}.hdr'.format(tile)
            prj_name = '{0}.prj'.format(tile)

            bil_path = os.path.join(elevation_dir, bil_name)
            hdr_path = os.path.join(elevation_dir, hdr_name)
            logger.debug('BIL Path: {0}'.format(bil_path))
            logger.debug('HDR Path: {0}'.format(hdr_path))

            if (os.path.isfile(bil_path) and
                    os.path.isfile(hdr_path)):

                # Link them to the current directory
                os.symlink(bil_path, bil_name)
                os.symlink(hdr_path, hdr_name)
                os.symlink(prj_path, prj_name)

                bil_list.append(bil_name)
                hdr_list.append(hdr_name)
                prj_list.append(prj_name)

            else:
                logger.debug('Missing Tile: {0}'.format(bil_name))
                missing_count += 1

        logger.debug('Expected Tile Count: {0}'.format(tile_count))
        logger.debug('Missing Tile Count: {0}'.format(missing_count))

        # Check if we are missing all the tiles, which indicates over water
        if missing_count >= tile_count:
            # Cleanup the tile links
            for file_name in bil_list:
                os.unlink(file_name)
            for file_name in hdr_list:
                os.unlink(file_name)
            for file_name in prj_list:
                os.unlink(file_name)
            raise GLSOverWaterError('GLS DEM is over water')

        logger.info('GLS DEM Files: {0}'.format(', '.join(bil_list)))

        # If the image crosses the 180 meridian, shift the west tile
        # longitudes to use the 0..360 range so the mosaic is not confused
        if start_longitude > 0 and end_longitude < 0:

            for tile in bil_list:
                hemisphere = tile[3:4]
                if hemisphere == "w":

                    # Name the shifted output file
                    shifted_tile = tile + '_shifted'

                    # Shift the longitude values
                    self.shift_longitude(tile, shifted_tile, 360)

                    # Remove symbolic link to original DEM data since we
                    # want to replace it with updated data
                    os.unlink(tile)

                    # Move destination file back to source file
                    output = ''
                    try:
                        cmd = 'mv {0} {1}'.format(shifted_tile, tile)
                        output = execute_cmd(cmd)
                    finally:
                        if len(output) > 0:
                            logger.info(output)

        # MOSAIC the tiles together
        self.mosaic_tiles(bil_list)

        # Warp to the source data
        self.warp_to_source_data(self.mosaic_image_name)

        # Cleanup intermediate data
        self.mosaic_cleanup()

        for file_name in bil_list:
            os.unlink(file_name)
        for file_name in hdr_list:
            os.unlink(file_name)
        for file_name in prj_list:
            os.unlink(file_name)

    def adjust_elevation_to_wgs84(self):
        """Adjusts the warped elevation to the WGS84 GEOID"""

        geoid_header_name = 'espa-geoid.hdr'
        geoid_image_name = 'espa-geoid.img'

        # Link the WGS84 GEOID data to the current directory
        if not os.path.exists(self.wgs84_image_name):
            # Should only need to test for one of them
            os.symlink(self.wgs84_header_path, self.wgs84_header_name)
            os.symlink(self.wgs84_image_path, self.wgs84_image_name)

        image_extents = {'min_x': self.min_x_extent,
                         'min_y': self.min_y_extent,
                         'max_x': self.max_x_extent,
                         'max_y': self.max_y_extent}

        # Warp the GEOID to the elevation/product projection
        Geo.warp(resampling_method=self.elevation_resampling_method,
                 resolution_x=self.pixel_resolution_x,
                 resolution_y=self.pixel_resolution_y,
                 target_srs=self.target_srs,
                 image_extents=image_extents,
                 output_data_type=self.elevation_type_int16,
                 output_format=self.elevation_format,
                 source_data=self.wgs84_image_name,
                 output_filename=geoid_image_name)

        # Remove the symlink to the WGS84 GEOID
        os.unlink(self.wgs84_header_name)
        os.unlink(self.wgs84_image_name)

        # Open the WGS84 and elevation datasets
        geoid_ds = gdal.Open(geoid_image_name)
        elevation_ds = gdal.Open(self.elevation_image_name)

        # Get the WGS84 and elevation band information
        geoid_band = geoid_ds.GetRasterBand(1)
        elevation_band = elevation_ds.GetRasterBand(1)

        # Verify they are the same size, otherwise something broke
        if (geoid_band.XSize != elevation_band.XSize or
                geoid_band.YSize != elevation_band.YSize):
            raise Exception('The size of the GEOID and elevation do not match')

        # Read the data from both into memory
        geoid_data = geoid_band.ReadAsArray(0, 0,
                                            geoid_band.XSize,
                                            geoid_band.YSize).astype(np.int16)
        elevation_data = (elevation_band
                          .ReadAsArray(0, 0,
                                       elevation_band.XSize,
                                       elevation_band.YSize).astype(np.int16))

        # Use numpy math to add the datasets together
        new_data = (elevation_data + geoid_data).astype(np.int16)

        # Write the updated data to the elevation filename
        with open(self.elevation_image_name, 'wb') as img_fd:
            new_data.tofile(img_fd)

        # Cleanup memory
        del new_data
        del elevation_data
        del elevation_band
        del elevation_ds
        del geoid_data
        del geoid_band
        del geoid_ds

        # Remove the warped GEOID data
        os.unlink(geoid_header_name)
        os.unlink(geoid_image_name)

    def append_band(self, metadata, band):
        """Implement this to add the band object to the metadata object"""
        raise NotImplementedError('Please Implement Me In {0}'
                                  .format(str(type(self))))

    def add_elevation_band_to_xml(self, elevation_source):
        """Adds the elevation band to the ESPA Metadata XML file"""

        metadata = Metadata(xml_filename=self.xml_filename)

        # Create an element maker
        em = objectify.ElementMaker(annotate=False,
                                    namespace=None,
                                    nsmap=None)

        # Create a band element
        band = em.band()

        # Set attributes for the band element
        band.set('product', 'elevation')
        band.set('source', elevation_source)
        band.set('name', 'elevation')
        band.set('category', 'image')
        band.set('data_type', 'INT16')
        band.set('nlines', str(self.number_of_lines))
        band.set('nsamps', str(self.number_of_samples))
        # Our current sources for elevation do not contain fill and we
        # populate the entire bounds of the image with elevation values
        # Setting to -9999 for consistency with our other INT16 products
        band.set('fill_value', '-9999')

        # Add elements to the band object
        band.short_name = em.element('ELEVATION')
        band.long_name = em.element('elevation')
        band.file_name = em.element(self.elevation_image_name)

        # Create a pixel size element
        band.pixel_size = em.element()
        # Add attrbutes to the pixel size object
        band.pixel_size.set('x', str(self.pixel_resolution_x))
        band.pixel_size.set('y', str(self.pixel_resolution_x))
        band.pixel_size.set('units', self.pixel_units)

        band.resample_method = em.element('bilinear')
        band.data_units = em.element('meters')

        # Set the software version
        band.app_version = em.element(SOFTWARE_VERSION)

        # Get the production date and time in string format
        # Strip the microseconds and add a Z
        date_now = ('{0}Z'.format(datetime.datetime.now()
                                  .strftime('%Y-%m-%dT%H:%M:%S')))
        band.production_date = em.element(date_now)

        # Append the band to the XML
        self.append_band(metadata, band)

        # Validate the XML
        metadata.validate()

        # Write it to the XML file
        metadata.write(xml_filename=self.xml_filename)

        # Memory cleanup
        del metadata

    def generate(self):
        """Generates the elevation"""

        logger = logging.getLogger(__name__)

        self.parse_metadata()

        # Just a bunch of debug reporting follows
        logger.debug('bounding_north_latitude = {0}'
                     .format(self.bounding_north_latitude))
        logger.debug('bounding_south_latitude = {0}'
                     .format(self.bounding_south_latitude))
        logger.debug('bounding_east_longitude = {0}'
                     .format(self.bounding_east_longitude))
        logger.debug('bounding_west_longitude = {0}'
                     .format(self.bounding_west_longitude))

        logger.debug('min_x_extent = {0}'.format(self.min_x_extent))
        logger.debug('max_y_extent = {0}'.format(self.max_y_extent))
        logger.debug('max_x_extent = {0}'.format(self.max_x_extent))
        logger.debug('min_y_extent = {0}'.format(self.min_y_extent))

        logger.debug('pixel_resolution_x = {0}'
                     .format(self.pixel_resolution_x))
        logger.debug('pixel_resolution_y = {0}'
                     .format(self.pixel_resolution_y))

        logger.debug('elevation_header_name = {0}'
                     .format(self.elevation_header_name))
        logger.debug('elevation_image_name = {0}'
                     .format(self.elevation_image_name))

        logger.debug('espa_elevation_dir = {0}'
                     .format(self.espa_elevation_dir))

        # Pad the max box coordinate values
        self.bounding_north_latitude += self.maxbox_padding
        self.bounding_south_latitude -= self.maxbox_padding

        self.bounding_east_longitude += self.maxbox_padding
        self.bounding_west_longitude -= self.maxbox_padding

        elevation_source = 'gtopo30'
        # Retrieve the tiles, mosaic, and warp to the source data
        if self.bounding_north_latitude <= self.ramp_south_limit:
            try:
                logger.info('Attempting to use RAMP DEM')
                self.generate_using_ramp()
                '''
                According to Landsat the RAMP DEM does not need adjusting to
                the WGS84 GEOID
                '''
                elevation_source = 'ramp'
            except RAMPCoverageError:
                logger.exception('RAMP DEM failed to cover input data'
                                 ' defaulting to GTOPO30')
                self.generate_using_gtopo30()
                self.adjust_elevation_to_wgs84()

        elif ((self.bounding_north_latitude <= self.glsdem_south_limit and
               self.bounding_north_latitude > self.ramp_south_limit and
               self.bounding_south_latitude <= self.glsdem_south_limit and
               self.bounding_south_latitude > self.ramp_south_limit) or
              (self.bounding_north_latitude >= self.glsdem_north_limit and
               self.bounding_south_latitude >= self.glsdem_north_limit)):

            logger.info('Using GTOPO30 DEM')
            self.generate_using_gtopo30()
            self.adjust_elevation_to_wgs84()

        else:
            print('nbound: ', self.bounding_north_latitude)
            print('sbound: ', self.bounding_south_latitude)
            print('wbound: ', self.bounding_west_longitude)
            print('ebound: ', self.bounding_east_longitude)
            try:
                logger.info('Attempting to use GLS DEM')
                self.generate_using_gls()
                elevation_source = 'gls'
            except GLSOverWaterError:
                logger.exception('GLS DEM over water defaulting to GTOPO30')
                self.generate_using_gtopo30()

            self.adjust_elevation_to_wgs84()

        # Cleanup the GDAL generated auxiliary files
        remove_list = glob.glob(self.gdal_aux_regexp)
        for file_name in remove_list:
            os.unlink(file_name)

        # Update the ENVI header
        # Specify the data type, because we were using Float32, but the final
        # was written as Int16.
        envi_header = ENVIHeader(self.elevation_header_name)
        envi_header.update_envi_header(band_names='band 1 - elevation',
                                       data_type=2,
                                       no_data_value=-9999)

        # Only add the elevation band to the XML file
        try:
            # Determine if we are processing using the XML
            getattr(self, 'xml_filename')
        except AttributeError:
            pass
        else:
            # We are processing using XML so add the band
            self.add_elevation_band_to_xml(elevation_source)


class XMLElevation(BaseElevation):
    """Defines the class object for XML based elevation generation

       If user_extents is True, then the user-specified min/max x and y
       geographic extents will be used, instead of the scene extents. However
       the scene projection and resolution will be used.
    """

    def __init__(self, xml_filename, user_extents, minx, maxx, miny,
                 maxy, nbound_lat, sbound_lat, wbound_lon, ebound_lon,
                 elev_filename):
        """Class initialization"""
        super(XMLElevation, self).__init__(elev_filename)

        self.xml_filename = xml_filename
        self.user_extents = user_extents
        if user_extents:
            self.min_x_extent = minx
            self.max_x_extent = maxx
            self.min_y_extent = miny
            self.max_y_extent = maxy
            self.bounding_north_latitude = nbound_lat
            self.bounding_south_latitude = sbound_lat
            self.bounding_west_longitude = wbound_lon
            self.bounding_east_longitude = ebound_lon

    def parse_metadata(self):
        """Parse the input metadata file

        Search for the desired fields in the metadata file, and set the
        associated class variables with the values read for that field.

        Notes:
          It is expected the input metadata file is an ESPA *.xml file and
          follows the format of those files.  Level-1, TOA reflectance, or
          surface reflectance products are supported as input.  Band 1 from
          those products will be used.
        """

        metadata = Metadata(xml_filename=self.xml_filename)
        metadata.parse(xml_filename=self.xml_filename)

        global_metadata = self.get_global_metadata(metadata)

        # Read the scene extents if they weren't specified by the user
        if not self.user_extents:
            self.bounding_north_latitude = float(global_metadata
                                                 .bounding_coordinates.north)
            self.bounding_south_latitude = float(global_metadata
                                                 .bounding_coordinates.south)
            self.bounding_east_longitude = float(global_metadata
                                                 .bounding_coordinates.east)
            self.bounding_west_longitude = float(global_metadata
                                                 .bounding_coordinates.west)

            for corner_point in (global_metadata
                                 .projection_information.corner_point):
                if corner_point.attrib['location'] == 'UL':
                    self.min_x_extent = float(corner_point.attrib['x'])
                    self.max_y_extent = float(corner_point.attrib['y'])
                if corner_point.attrib['location'] == 'LR':
                    self.max_x_extent = float(corner_point.attrib['x'])
                    self.min_y_extent = float(corner_point.attrib['y'])

            self.grid_origin = global_metadata.projection_information.grid_origin

        # Read the rest of the scene metadata
        product_id = None
        for element in global_metadata.getchildren():
            if 'product_id' in element.tag:
                product_id = element.text
            elif 'scene_id' in element.tag:
                product_id = element.text
        if product_id is None:
            raise RuntimeError('Un-Supported Metadata XML')

        self.elevation_header_name = (self.elevation_header_name_fmt
                                      .format(product_id))
        self.elevation_image_name = (self.elevation_image_name_fmt
                                     .format(product_id))

        if str(metadata.xml_object.tag).endswith('espa_metadata'):
            bands = metadata.xml_object.bands.band
        elif str(metadata.xml_object.tag).endswith('ard_metadata'):
            bands = metadata.xml_object.tile_metadata.bands.band

        ref_band = self.get_reference_band(bands)
        # Make sure an appropriate band was found in the XML file
        if ref_band is None:
            raise RuntimeError('Supported bands not found in XML file')

        self.target_srs = Geo.get_proj4_projection_string(str(ref_band.file_name))
        self.pixel_resolution_x = float(ref_band.pixel_size.attrib['x'])
        self.pixel_resolution_y = float(ref_band.pixel_size.attrib['y'])
        self.pixel_units = ref_band.pixel_size.attrib['units']
        self.number_of_lines = ref_band.attrib['nlines']
        self.number_of_samples = ref_band.attrib['nsamps']

        # Adjust the coordinates for image extents from the XML if they are
        # in center of pixel, as we need to supply the warping with actual
        # extents
        if not self.user_extents and self.grid_origin == 'CENTER':
            self.min_x_extent = (self.min_x_extent -
                                 self.pixel_resolution_x * 0.5)
            self.max_x_extent = (self.max_x_extent +
                                 self.pixel_resolution_x * 0.5)
            self.min_y_extent = (self.min_y_extent -
                                 self.pixel_resolution_y * 0.5)
            self.max_y_extent = (self.max_y_extent +
                                 self.pixel_resolution_y * 0.5)

        # Determine the number of lines and samples for the user-specified
        # extents, based on the pixel size
        if not self.user_extents:
            self.number_of_samples = int(round((self.max_x_extent - self.min_x_extent) / self.pixel_resolution_x))
            self.number_of_lines = int(round((self.max_y_extent - self.min_y_extent) / self.pixel_resolution_y))

        del metadata


ESPA_PRODUCT_NAMES = ['L1T', 'L1G', 'L1TP', 'L1GT', 'L1GS', 'sr_refl']
ESPA_BAND_NAMES = ['b1', 'sr_band1']


class ESPAXMLElevation(XMLElevation):

    def __init__(self, xml_filename, user_extents, minx, maxx, miny,
                 maxy, nbound_lat, sbound_lat, wbound_lon, ebound_lon,
                 elev_filename):
        """Class initialization"""
        super(ESPAXMLElevation, self).__init__(xml_filename, user_extents,
                                               minx, maxx, miny, maxy,
                                               nbound_lat, sbound_lat,
                                               wbound_lon, ebound_lon,
                                               elev_filename)

    def get_global_metadata(self, metadata):
        """Retrieves the global metadata for ESPA
        """

        return metadata.xml_object.global_metadata

    def append_band(self, metadata, band):
        """Appends the band to the correct location for ESPA
        """

        metadata.xml_object.bands.append(band)

    def get_reference_band(self, bands):
        """Determines the correct reference band for ESPA
        """

        reference_band = None

        for band in bands:
            if (band.attrib['name'] in ESPA_BAND_NAMES and
                    band.attrib['product'] in ESPA_PRODUCT_NAMES):
                if os.path.isfile(str(band.file_name)):
                    reference_band = band
                    break

        return reference_band


# The PIXELQA band is present in all ARD Tile products
ARD_PRODUCT_NAMES = ['level2_qa']
ARD_BAND_NAMES = ['PIXELQA']


class ARDXMLElevation(XMLElevation):

    def __init__(self, xml_filename, user_extents, minx, maxx, miny,
                 maxy, nbound_lat, sbound_lat, wbound_lon, ebound_lon,
                 elev_filename):
        """Class initialization"""
        super(ARDXMLElevation, self).__init__(xml_filename, user_extents,
                                              minx, maxx, miny, maxy,
                                              nbound_lat, sbound_lat,
                                              wbound_lon, ebound_lon,
                                              elev_filename)

    def get_global_metadata(self, metadata):
        """Retrieves the global metadata for ARD
        """

        return metadata.xml_object.tile_metadata.global_metadata

    def append_band(self, metadata, band):
        """Appends the band to the correct location for ARD
        """

        metadata.xml_object.tile_metadata.bands.append(band)

    def get_reference_band(self, bands):
        """Determines the correct reference band for ARD
        """

        reference_band = None

        for band in bands:
            if (band.attrib['name'] in ARD_BAND_NAMES and
                    band.attrib['product'] in ARD_PRODUCT_NAMES):
                if os.path.isfile(str(band.file_name)):
                    reference_band = band
                    break

        return reference_band


class MTLElevation(BaseElevation):
    """Defines the class object for MTL based elevation generation

       If user_extents is True, then the user-specified min/max x and y
       geographic extents will be used, instead of the scene extents. However
       the scene projection and resolution will be used.
    """

    def __init__(self, mtl_filename, user_extents, minx, maxx, miny,
                 maxy, nbound_lat, sbound_lat, wbound_lon, ebound_lon,
                 elev_filename):
        """Class initialization"""
        super(MTLElevation, self).__init__(elev_filename)

        self.mtl_filename = mtl_filename
        self.user_extents = user_extents
        if user_extents:
            self.min_x_extent = minx
            self.max_x_extent = maxx
            self.min_y_extent = miny
            self.max_y_extent = maxy
            self.bounding_north_latitude = nbound_lat
            self.bounding_south_latitude = sbound_lat
            self.bounding_west_longitude = wbound_lon
            self.bounding_east_longitude = ebound_lon

    def parse_metadata(self):
        """Parse the input metadata file

        Search for the desired fields in the metadata file, and set the
        associated class variables with the values read for that field.

        Notes:
          1. It is expected the input metadata file is an LPGS _MTL.txt file and
             follows the format (contains the same fields) of those files.
          2. Number of lines and samples is not needed since the DEM is only
             written to the XML file if an XML file is being processed.
        """

        # Get the logger
        logger = logging.getLogger(__name__)

        file_name_band_1 = None
        product_id = None

        # open the metadata file for reading
        with open(self.mtl_filename, 'r') as mtl_fd:

            # read and process one line at a time, using the = sign as the
            # deliminator for the desired parameters.  remove the trailing
            # end of line and leading/trailing white space
            for line in mtl_fd:
                myline = line.rstrip('\r\n').strip()
                # logger.debug('DEBUG: [{0}]'.format(myline))
                # break out if at the end of the metadata in the metadata file
                if myline == 'END':
                    break

                # process the myline which should be parameter = value strings
                # some strings may need the "s stripped from the value itself
                (param, value) = myline.split('=', 1)
                param = param.strip()
                value = value.strip()
                try:
                    f_value = float(value)
                except ValueError:
                    pass
                # logger.debug('    DEBUG: param [{0}]'.format(param))
                # logger.debug('    DEBUG: value [{0}]'
                #              .format(value.strip('\"')))
                # Read the extents only if the user-specified extents were
                # not provided
                if param == 'CORNER_UL_LAT_PRODUCT' and not self.user_extents:
                    if f_value > self.bounding_north_latitude:
                        self.bounding_north_latitude = f_value
                elif param == 'CORNER_UR_LAT_PRODUCT' and not self.user_extents:
                    if f_value > self.bounding_north_latitude:
                        self.bounding_north_latitude = f_value
                elif param == 'CORNER_LL_LAT_PRODUCT' and not self.user_extents:
                    if f_value < self.bounding_south_latitude:
                        self.bounding_south_latitude = f_value
                elif param == 'CORNER_LR_LAT_PRODUCT' and not self.user_extents:
                    if f_value < self.bounding_south_latitude:
                        self.bounding_south_latitude = f_value
                elif param == 'CORNER_UL_LON_PRODUCT' and not self.user_extents:
                    if f_value < self.bounding_west_longitude:
                        self.bounding_west_longitude = f_value
                elif param == 'CORNER_UR_LON_PRODUCT' and not self.user_extents:
                    if f_value > self.bounding_east_longitude:
                        self.bounding_east_longitude = f_value
                elif param == 'CORNER_LL_LON_PRODUCT' and not self.user_extents:
                    if f_value < self.bounding_west_longitude:
                        self.bounding_west_longitude = f_value
                elif param == 'CORNER_LR_LON_PRODUCT' and not self.user_extents:
                    if f_value > self.bounding_east_longitude:
                        self.bounding_east_longitude = f_value
                elif param == 'CORNER_UL_PROJECTION_X_PRODUCT' and    \
                     not self.user_extents:
                    self.min_x_extent = f_value
                elif param == 'CORNER_UL_PROJECTION_Y_PRODUCT' and    \
                     not self.user_extents:
                    self.max_y_extent = f_value
                elif param == 'CORNER_LR_PROJECTION_X_PRODUCT' and    \
                     not self.user_extents:
                    self.max_x_extent = f_value
                elif param == 'CORNER_LR_PROJECTION_Y_PRODUCT' and    \
                     not self.user_extents:
                    self.min_y_extent = f_value
                elif param == 'GRID_CELL_SIZE_REFLECTIVE':
                    self.pixel_resolution_x = f_value
                    self.pixel_resolution_y = f_value
                elif param == 'LANDSAT_SCENE_ID':
                    product_id = value.strip('\"')
                elif param == 'FILE_NAME_BAND_1':
                    file_name_band_1 = value.strip('\"')

        # validate retrieval of parameters
        if self.bounding_north_latitude == -9999.0:
            raise RuntimeError('Obtaining north bounding metadata field from:'
                               ' [{0}]'.format(self.mtl_filename))

        if self.bounding_south_latitude == 9999.0:
            raise RuntimeError('Obtaining south bounding metadata field from:'
                               ' [{0}]'.format(self.mtl_filename))

        if self.bounding_east_longitude == -9999.0:
            raise RuntimeError('Obtaining east bounding metadata field from:'
                               ' [{0}]'.format(self.mtl_filename))

        if self.bounding_west_longitude == 9999.0:
            raise RuntimeError('Obtaining west bounding metadata field from:'
                               ' [{0}]'.format(self.mtl_filename))

        if self.min_x_extent is None:
            raise RuntimeError('Obtaining UL Map X field from: [{0}]'
                               .format(self.mtl_filename))

        if self.max_y_extent is None:
            raise RuntimeError('Obtaining UL Map Y field from: [{0}]'
                               .format(self.mtl_filename))

        if self.max_x_extent is None:
            raise RuntimeError('Obtaining LR Map X field from: [{0}]'
                               .format(self.mtl_filename))

        if self.min_y_extent is None:
            raise RuntimeError('Obtaining LR Map Y field from: [{0}]'
                               .format(self.mtl_filename))

        if self.pixel_resolution_x is None:
            raise RuntimeError('Obtaining reflective grid cell size field'
                               ' from: [{0}]'.format(self.mtl_filename))

        if self.pixel_resolution_y is None:
            raise RuntimeError('Obtaining reflective grid cell size field'
                               ' from: [{0}]'.format(self.mtl_filename))

        if file_name_band_1 is None:
            raise RuntimeError('Obtaining FILE_NAME_BAND_1 field from: [{0}]'
                               .format(self.mtl_filename))

        if product_id is None:
            raise RuntimeError('Obtaining LANDSAT_SCENE_ID field from: [{0}]'
                               .format(self.mtl_filename))

        self.elevation_header_name = (self.elevation_header_name_fmt
                                      .format(product_id))
        self.elevation_image_name = (self.elevation_image_name_fmt
                                     .format(product_id))

        self.target_srs = Geo.get_proj4_projection_string(file_name_band_1)

        # Adjust the coordinates for image extents from the MTL because they
        # are in center of pixel, and we need to supply the warping with actual
        # extents
        if not self.user_extents:
            self.min_x_extent = (self.min_x_extent -
                                 self.pixel_resolution_x * 0.5)
            self.max_x_extent = (self.max_x_extent +
                                 self.pixel_resolution_x * 0.5)
            self.min_y_extent = (self.min_y_extent -
                                 self.pixel_resolution_y * 0.5)
            self.max_y_extent = (self.max_y_extent +
                                 self.pixel_resolution_y * 0.5)


def check_for_extents(args):
    """Were custom extents specified?  If so, all extents must be specified.
    Args:
        args <args>: Command line arguments

    Returns:
        <bool>: True if cusom extents were specified, and False if not
    """

    if (args.extent_minx is not None or args.extent_maxx is not None or
            args.extent_miny is not None or args.extent_maxy is not None or
            args.nbound_lat is not None or args.sbound_lat is not None or
            args.wbound_lon is not None or args.ebound_lon is not None):

        # One of the user-specified extents was specified, so make sure all
        # were specified
        if args.extent_minx is None:
            raise RuntimeError('Must specify --extent-minx when specifying '
                               'custom extents')

        if args.extent_maxx is None:
            raise RuntimeError('Must specify --extent-maxx when specifying '
                               'custom extents')

        if args.extent_miny is None:
            raise RuntimeError('Must specify --extent-miny when specifying '
                               'custom extents')

        if args.extent_maxy is None:
            raise RuntimeError('Must specify --extent-maxy when specifying '
                               'custom extents')

        if args.nbound_lat is None:
            raise RuntimeError('Must specify --nbound-lat when specifying '
                               'custom extents')

        if args.sbound_lat is None:
            raise RuntimeError('Must specify --sbound-lat when specifying '
                               'custom extents')

        if args.wbound_lon is None:
            raise RuntimeError('Must specify --wbound-lon when specifying '
                               'custom extents')

        if args.ebound_lon is None:
            raise RuntimeError('Must specify --ebound-lon when specifying '
                               'custom extents')

        return True

    return False


def main():
    """Provides the main processing for the script"""

    # get the command line argument for the metadata file
    description = ('Create an elevation band using either the MTL or XML '
                   'metadata as the information source. Optionally the scene '
                   'extents can be overriden with user-specified extents.')
    parser = ArgumentParser(description=description)

    parser.add_argument('--debug',
                        action='store_true',
                        dest='debug',
                        default=False,
                        help='turn debug logging on')

    parser.add_argument('--elevation',
                        action='store',
                        dest='elevation_filename',
                        default=None,
                        help='optional name of output elevation file (.img); '
                             'default is {scene_name}_elevation.img',
                        metavar='FILE',
                        required=False)

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument('--mtl', '--mtl_filename',
                       action='store',
                       dest='mtl_filename',
                       default=None,
                       help='name of Landsat MTL file',
                       metavar='FILE')

    group.add_argument('--xml', '--xml_filename',
                       action='store',
                       dest='xml_filename',
                       default=None,
                       help='name of XML Metadata file',
                       metavar='FILE')

    # Look for user-specified min/max extents, which would then override the
    # scene extents
    geo_extents = parser.add_argument_group('geo_extents',
        'User-specified geographic extents to override the scene extents. '
        'The scene projection and reflectance band resolution are used. '
        'If one of the following parameters is specified they all must be '
        'specified.')

    geo_extents.add_argument('--extent-minx',
                             action='store',
                             dest='extent_minx',
                             default=None,
                             metavar='FLOAT',
                             help='Minimum X direction extent value',
                             required=False)

    geo_extents.add_argument('--extent-maxx',
                             action='store',
                             dest='extent_maxx',
                             default=None,
                             metavar='FLOAT',
                             help='Maximum X direction extent value',
                             required=False)

    geo_extents.add_argument('--extent-miny',
                             action='store',
                             dest='extent_miny',
                             default=None,
                             metavar='FLOAT',
                             help='Minimum Y direction extent value',
                             required=False)

    geo_extents.add_argument('--extent-maxy',
                             action='store',
                             dest='extent_maxy',
                             default=None,
                             metavar='FLOAT',
                             help='Maximum Y direction extent value',
                             required=False)

    geo_extents.add_argument('--nbound-lat',
                             action='store',
                             dest='nbound_lat',
                             default=None,
                             metavar='FLOAT',
                             help='North-bounding latitude associated with '
                                  'extent-maxy',
                             required=False)

    geo_extents.add_argument('--sbound-lat',
                             action='store',
                             dest='sbound_lat',
                             default=None,
                             metavar='FLOAT',
                             help='South-bounding latitude associated with '
                                  'extent-miny',
                             required=False)

    geo_extents.add_argument('--wbound-lon',
                             action='store',
                             dest='wbound_lon',
                             default=None,
                             metavar='FLOAT',
                             help='West-bounding longitude associated with '
                                  'extent-minx',
                             required=False)

    geo_extents.add_argument('--ebound-lon',
                             action='store',
                             dest='ebound_lon',
                             default=None,
                             metavar='FLOAT',
                             help='East-bounding longitude associated with '
                                  'extent-maxx',
                             required=False)

    args = parser.parse_args()

    # Check logging level
    logging_level = logging.INFO
    if args.debug:
        logging_level = logging.DEBUG

    # Setup the default logger format and level.  Log to STDOUT.
    logging.basicConfig(format=('%(asctime)s.%(msecs)03d %(process)d'
                                ' %(levelname)-8s'
                                ' %(filename)s:%(lineno)d:'
                                '%(funcName)s -- %(message)s'),
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging_level,
                        stream=sys.stdout)

    logger = logging.getLogger(__name__)

    # Get the environment variable for the elevation data directory
    if ESPA_ELEVATION_DIR not in os.environ:
        logger.info('{0} environment variable not defined'
                    .format(ESPA_ELEVATION_DIR))
        sys.exit(1)  # EXIT_FAILURE

    # Initialize
    minx = None
    miny = None
    maxx = None
    maxy = None
    nbound_lat = None
    sbound_lat = None
    wbound_lon = None
    ebound_lon = None
    elev_filename = args.elevation_filename

    # Grab the user-specified extents if they exist
    user_extents = check_for_extents(args)
    if user_extents:
        minx = float(args.extent_minx)
        miny = float(args.extent_miny)
        maxx = float(args.extent_maxx)
        maxy = float(args.extent_maxy)
        nbound_lat = float(args.nbound_lat)
        sbound_lat = float(args.sbound_lat)
        wbound_lon = float(args.wbound_lon)
        ebound_lon = float(args.ebound_lon)
        logger.info('User-specified geographic extents will be used: '
                    'extent-minx: {0}  '
                    'extent-maxx: {1}  '
                    'extent-miny: {2}  '
                    'extent-maxy: {3}  '
                    'nbound-lat: {4}  '
                    'sbound-lat: {5}  '
                    'ebound-lon: {6}  '
                    'wbound-lon: {7}'.format(minx, maxx, miny, maxy, nbound_lat,
                                             sbound_lat, wbound_lon, ebound_lon))

    # Call the core processing
    elevation = None
    if args.xml_filename is not None:
        logger.info('Processing XML file: {0}'.format(args.xml_filename))

        metadata = Metadata(xml_filename=args.xml_filename)
        is_espa = False
        if str(metadata.xml_object.tag).endswith('espa_metadata'):
            is_espa = True
        elif str(metadata.xml_object.tag).endswith('ard_metadata'):
            is_espa = False
        else:
            raise RuntimeError('Unsupported Metadata XML --> {}'
                               .format(str(metadata.xml_object.tag)))
        del metadata

        if is_espa:
            elevation = ESPAXMLElevation(args.xml_filename, user_extents,
                                         minx, maxx, miny, maxy,
                                         nbound_lat, sbound_lat, wbound_lon,
                                         ebound_lon, elev_filename)
        else:
            elevation = ARDXMLElevation(args.xml_filename, user_extents,
                                        minx, maxx, miny, maxy,
                                        nbound_lat, sbound_lat, wbound_lon,
                                        ebound_lon, elev_filename)
    else:
        logger.info('Processing MTL file: {0}'.format(args.mtl_filename))

        elevation = MTLElevation(args.mtl_filename, user_extents, minx, maxx,
                                 miny, maxy, nbound_lat, sbound_lat, wbound_lon,
                                 ebound_lon, elev_filename)

    try:
        elevation.generate()
    except Exception:
        logger.exception('Elevation generation failed')
        sys.exit(1)  # EXIT_FAILURE

    sys.exit(0)  # EXIT_SUCCESS


if __name__ == '__main__':
    main()
