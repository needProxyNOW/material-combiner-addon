import numpy as np
import array

import bpy

# A 'pixel buffer' is a single precision float type numpy array, viewed in the shape
# (image.height, image.width, image.channels)

# Image.pixels is a bpy_prop_array, to use its foreach_get/foreach_set methods with buffers, the buffer's type has to
# match the internal C type used by Blender, otherwise Blender will reject the buffer.
#
# Note that this is different to the behaviour of the foreach_get and foreach_set methods on bpy_prop_collection objects
# which allow for the type to be different by casting every value to the new type (which you generally want to avoid
# anyway because it slows things down)
# Single precision float dtype for use with numpy functions
pixel_dtype = np.single
# The C type code for single precision float, for use with Python arrays
pixel_ctype = 'f'


if bpy.app.version >= (2, 83):  # bpy_prop_array.foreach_get was added in Blender 2.83
    # 1.6ms for 1024x1024
    # 15.2ms for 2048x2048
    # 60.9ms for 4096x4096
    # 306.2ms for 8192x8192
    def __get_buffer_internal(image):
        pixels = image.pixels
        buffer = np.empty(len(pixels), dtype=pixel_dtype)
        # Buffer must be flat when reading
        pixels.foreach_get(buffer)
        return buffer
elif bpy.app.version >= (2, 80):  # Being able to use the memory of an existing buffer in bgl.Buffer was added in Blender 2.80, not that this behaviour is documented
    import bgl
    pixel_gltype = bgl.GL_FLOAT
    # 16.7ms for 1024x1024
    # 65.9ms for 2048x2048
    # 293.9ms for 4096x4096
    # 1121.6ms for 8192x8192

    # see https://blender.stackexchange.com/a/230242 for details
    def __get_buffer_internal(image):
        # TODO: Check that transparency doesn't premultiply even if the image is set to premultiply, we want the raw
        #  pixels!
        pixels = image.pixels
        # Load the image into OpenGL and use that to get the pixels in a more performant manner
        # As per the documentation, the colours will be read in scene linear color space and have premultiplied or
        # straight alpha matching the image alpha mode.
        # TODO: Temporarily set alpha mode to STRAIGHT if image is set to PREMULTIPLY?
        # see https://blender.stackexchange.com/a/230242 for details
        # Open GL will cache the image if we've used it previously, this means that if we update the image in Blender
        # it won't have updated in Open GL unless we free it first. There isn't really a way to know if the image has
        # changed since it was last cached, so we'll free it
        if image.bindcode:
            # If the open gl bindcode is set, then it's already been cached, so free it from open gl first
            image.gl_free()
        if image.gl_load():
            print("Could not load {} into Open GL, resorting to a slower method of getting pixels".format(image))
            return np.fromiter(pixels, dtype=pixel_dtype)
        bgl.glActiveTexture(bgl.GL_TEXTURE0)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, image.bindcode)
        buffer = np.empty(len(pixels), dtype=pixel_dtype)
        gl_buffer = bgl.Buffer(bgl.GL_FLOAT, buffer.shape, buffer)
        bgl.glGetTexImage(bgl.GL_TEXTURE_2D, 0, bgl.GL_RGBA, bgl.GL_FLOAT, gl_buffer)
        return buffer
else:  # Oldest theoretically supported Blender version is 2.50, because that's when the bgl module was added
    import bgl
    pixel_gltype = bgl.GL_FLOAT

    try:
        from .ctypes_buffer_utils import gl_get_tex_image_to_numpy

        def __2_79_gl_tex_to_np(num_pixel_components):
            return gl_get_tex_image_to_numpy(num_pixel_components, pixel_gltype, pixel_dtype)
    except AssertionError:
        print("Failed to import ctypes_buffer_utils, resorting to using much slower iteration to get image pixels from Open GL")

        def __2_79_gl_tex_to_np(num_pixel_components):
            gl_buffer = bgl.Buffer(pixel_gltype, num_pixel_components)
            bgl.glGetTexImage(bgl.GL_TEXTURE_2D, 0, bgl.GL_RGBA, pixel_gltype, gl_buffer)
            return np.fromiter(gl_buffer, dtype=pixel_dtype)

    # On Blender 2.79:
    # Getting pixels through Open GL and then into a numpy array via gl_get_tex_image_to_numpy
    # 9.7ms for 1024x1024
    # 52.7ms for 2048x2048
    # 201.8ms for 4096x4096
    # 818.8ms for 8192x8192
    #
    # Getting pixels through Open GL and then into a numpy array via np.fromiter(buffer, dtype=pixel_dtype)
    # 159.6ms for 1024x1024
    # 636.5ms for 2048x2048
    # 2600.7ms for 4096x4096
    # 10215.1ms for 8192x8192
    #
    # Compared to simply "return np.fromiter(pixels, dtype=pixel_dtype)"
    # 200.3ms for 1024x1024
    # 819.8ms for 2048x2048
    # 3343.8 for 4096x4096
    # 33066.2 for 8192x8192
    def __get_buffer_internal(image):
        pixels = image.pixels
        if image.bindcode[0]:
            image.gl_free()
        if image.gl_load(0, bgl.GL_NEAREST, bgl.GL_NEAREST):
            print("Could not load {} into Open GL, resorting to a slower method of getting pixels".format(image))
            return np.fromiter(pixels, dtype=pixel_dtype)
        num_pixel_components = len(pixels)
        bgl.glEnable(bgl.GL_TEXTURE_2D)
        bgl.glActiveTexture(bgl.GL_TEXTURE0)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, image.bindcode[0])
        return __2_79_gl_tex_to_np(num_pixel_components)

if bpy.app.version >= (2, 83):
    def __write_pixel_buffer_internal(img, buffer):
        # buffer must be flattened when writing
        img.pixels.foreach_set(buffer.ravel())
else:
    try:
        from .ctypes_fast_pixel_write import set_pixels_matrix_hack

        # Performs a direct memory copy, so is almost as fast as foreach_set from Blender 2.83 and newer. It might work
        # as far back as Blender 2.63, but has only been tested as far back as Blender 2.79
        # 7.8ms for 1024x1024
        # 35.7ms for 2048x2048
        # 135.8ms for 4096x4096
        # 701.7ms for 8192x8192
        def __write_pixel_buffer_internal(img, buffer):
            set_pixels_matrix_hack(img, buffer)

    except AssertionError:
        print("Failed to import ctypes_fast_pixel_write, resorting to using 10 times slower method to set image pixels")

        # Added in Blender 2.83, here for reference
        # 7.6ms for 1024x1024
        # 29.6ms for 2048x2048
        # 114.7ms for 4096x4096
        # 471.5ms for 8192x8192
        # img.pixels.foreach_set(buffer)
        #
        # From a thread I found discussing the performance of Image.pixels, this was considered the fastest method
        # 110.6ms for 1024x1024
        # 1991.8ms for 4096x4096
        # img.pixels[:] = buffer.tolist()
        #
        # In most cases, it's faster to set the value of each element instead of replacing the entire pixels attribute,
        # but that doesn't seem to be the case for Python arrays for some reason.
        # I would have thought that maybe this was to do with Python arrays implementing the buffer protocol,
        # but then img.pixels = buffer.data (a MemoryView object, which also implements the buffer protocol) should also
        # be faster, but it's not.
        # buffer.tobytes() seems to be the fastest way to get an ndarray into a Python array
        # 85.5ms for 1024x1024
        # 388.2 for 2048x2048
        # 1511.1ms for 4096x4096
        # 6407.5ms for 8192x8192
        def __write_pixel_buffer_internal(img, buffer):
            img.pixels = array.array(pixel_ctype, buffer.tobytes())

linear_colorspaces = {'Linear', 'Non-Color', 'Raw'}
supported_colorspaces = linear_colorspaces | {'sRGB'}


def buffer_convert_linear_to_srgb(buffer):
    # Alpha is always linear, so get a view of only RGB.
    rgb_only_view = buffer[:, :, :3]

    is_small = rgb_only_view < 0.0031308

    small_rgb = rgb_only_view[is_small]
    # This can probably be optimised
    rgb_only_view[is_small] = np.where(small_rgb < 0.0, 0, small_rgb * 12.92)

    is_not_small = np.invert(is_small, out=is_small)

    rgb_only_view[is_not_small] = 1.055 * (rgb_only_view[is_not_small] ** (1.0 / 2.4)) - 0.055


def buffer_convert_srgb_to_linear(buffer):
    # Alpha is always linear, so get a view of only RGB.
    rgb_only_view = buffer[:, :, :3]

    is_small = rgb_only_view < 0.04045

    small_rgb = rgb_only_view[is_small]
    # This can probably be optimised
    rgb_only_view[is_small] = np.where(small_rgb < 0.0, 0, small_rgb / 12.92)

    is_not_small = np.invert(is_small, out=is_small)

    rgb_only_view[is_not_small] = ((rgb_only_view[is_not_small] + 0.055) / 1.055) ** 2.4


def get_pixel_buffer(img, atlas_colorspace='sRGB'):
    width, height = img.size
    channels = img.channels
    buffer = __get_buffer_internal(img)
    # View the buffer in a shape that better represents the data
    buffer.shape = (height, width, channels)

    # Pixels are always read raw, meaning that changing the colorspace of the image has no effect on the pixels,
    # but if we want to combine an X colorspace image into a Y colorspace atlas such that the X colorspace image appears
    # the same when viewed in Y colorspace, we need to pre-convert it from X colorspace to Y colorspace.
    img_color_space = img.colorspace_settings.name
    if atlas_colorspace == 'sRGB':
        if img_color_space == 'sRGB':
            return buffer
        elif img_color_space in linear_colorspaces:
            # Need to convert from Linear to sRGB
            buffer_convert_linear_to_srgb(buffer)
            return buffer
        else:
            raise TypeError("Unsupported image colorspace {} for {}. Must be in {}.".format(img_color_space, img, supported_colorspaces))
    elif atlas_colorspace in linear_colorspaces:
        if img_color_space in linear_colorspaces:
            return buffer
        elif img_color_space == 'sRGB':
            # Need to convert from sRGB to linear
            buffer_convert_srgb_to_linear(buffer)
            return buffer
    else:
        raise TypeError("Unsupported atlas colorspace {}. Must be in {}".format(atlas_colorspace, supported_colorspaces))


# Copy the image, resize the copy and then get the pixel buffer, the copied image is then destroyed
# The alternative would be to resize the passed in image and then reload it afterwards, but if the passed in image was
# dirty, then those dirty changes would be lost.
def get_resized_pixel_buffer(img, size):
    # Copy the input image
    copy = img.copy()
    # Scale (resize) the copy
    copy.scale(size[0], size[1])
    # Get the pixel buffer for the scaled copy
    buffer = get_pixel_buffer(copy)
    # Delete the scaled copy
    bpy.data.images.remove(copy)
    return buffer


def buffer_to_image(buffer, *, name):
    image = bpy.data.images.new(name, buffer.shape[1], buffer.shape[0], alpha=buffer.shape[2] == 4)
    write_pixel_buffer(image, buffer)
    return image


def write_pixel_buffer(img, buffer):
    width, height = img.size
    image_shape = (height, width, img.channels)
    if buffer.shape == image_shape:
        __write_pixel_buffer_internal(img, buffer)
    else:
        raise RuntimeError("Buffer shape {} does not match image shape {}".format(buffer.shape, image_shape))


def new_pixel_buffer(size, color=(0.0, 0.0, 0.0, 0.0)):
    """Create a new blank pixel buffer.
    The number of channels is determined based on the fill color.
    Default fill color is transparent black.
    Compared to how pixels are usually accessed in Blender where (0,0) is the bottom left pixel, pixel buffers have the
    y-axis flipped so that (0,0) is the top left of the image
    :return: a new pixel buffer ndarray
    """
    width, height = size
    # rgba
    channels = len(color)
    if channels > 4 or channels == 0:
        raise TypeError("A color can have between 1 and 4 (inclusive) components, but found {} in {}".format(channels, color))
    buffer = np.full((height, width, channels), fill_value=color, dtype=pixel_dtype)
    return buffer


def pixel_buffer_paste(target_buffer, source_buffer_or_pixel, corner_or_box):
    # box coordinates treat (0,0) as top left, but bottom left is (0,0) in blender, so view the buffer with flipped
    # y-axis
    target_buffer = target_buffer[::-1, :, :]
    if isinstance(source_buffer_or_pixel, np.ndarray):
        source_dimensions = len(source_buffer_or_pixel.shape)
        if source_dimensions == 3:
            # Source is a buffer representing a 2D image, with the 3rd axis being the pixel data
            source_is_pixel = False
        elif source_dimensions == 1 and target_buffer.shape[-1] >= source_dimensions:
            # Source is the data for a single pixel, to be pasted into all the pixels in the box region
            source_is_pixel = True
        else:
            raise TypeError("source buffer or pixel could not be parsed for pasting")
    elif isinstance(source_buffer_or_pixel, (tuple, list)) and target_buffer.shape[-1] >= len(source_buffer_or_pixel):
        # Source is the data for a single pixel, to be pasted into all the pixels in the box region
        source_is_pixel = True
    else:
        raise TypeError("source pixel could not be parsed for pasting")

    def fit_box(box):
        # Fit the box to the image. This could be changed to raise an Error if the box doesn't fit.
        # Remember that box corners are cartesian coordinates where (0,0) is the top left corner of the top left pixel
        # and (1,1) is the bottom right corner of the top left pixel
        left, upper, right, lower = box
        left = max(left, 0)
        upper = max(upper, 0)
        right = min(right, target_buffer.shape[1] + 1)
        lower = min(lower, target_buffer.shape[0] + 1)
        return left, upper, right, lower

    if source_is_pixel:
        # When the source is a single pixel color, there must be a box to paste to
        if len(corner_or_box) != 4:
            raise TypeError("When pasting a pixel color, a box region to paste to must be supplied, but got: {}".format(corner_or_box))
        left, upper, right, lower = fit_box(corner_or_box)
        # Fill the box with corners (left, upper) and (right, lower) with the pixel color, filling in as many components
        # of the pixels as in the source pixel.
        # Remember that these corners are cartesian coordinates with (0,0) as the top left corner of the image.
        # A box with corners (0,0) and (1,1) only contains the pixels between (0,0) inclusive and (1,1) exclusive
        num_source_channels = len(source_buffer_or_pixel)
        print("DEBUG: Pasting into box {} colour {}".format((left, upper, right, lower), source_buffer_or_pixel))
        target_buffer[upper:lower, left:right, :num_source_channels] = source_buffer_or_pixel
    else:
        # box coordinates treat (0,0) as top left, but bottom left is (0,0) in blender, so view the buffer with flipped
        # y-axis
        source_buffer = source_buffer_or_pixel[::-1, :, :]
        # Parse a corner into a box
        if len(corner_or_box) == 2:
            # Only the top left corner to place the source buffer has been set, we will figure out the bottom right
            # corner
            left, upper = corner_or_box
            right = left + source_buffer.shape[1]
            lower = upper + source_buffer.shape[0]
        elif len(corner_or_box) == 4:
            left, upper, right, lower = corner_or_box
        else:
            raise TypeError("corner or box must be either a 2-tuple or 4-tuple, but was: {}".format(corner_or_box))

        if target_buffer.shape[-1] >= source_buffer.shape[-1]:
            fit_left, fit_upper, fit_right, fit_lower = fit_box((left, upper, right, lower))
            if fit_left != left or fit_upper != upper or fit_right != right or fit_lower != lower:
                print('DEBUG: Image to be pasted did not fit into target image, {} -> {}'.format((left, upper, right, lower), (fit_left, fit_upper, fit_right, fit_lower)))
            # If the pasted buffer can extend outside the source image, we need to figure out the area which fits within
            # the source image
            source_left = fit_left - left
            source_upper = fit_upper - upper
            source_right = source_buffer.shape[1] - right + fit_right
            source_lower = source_buffer.shape[0] - lower + fit_lower
            num_source_channels = source_buffer.shape[2]
            print("DEBUG: Pasting into box {} of target from box {} of source".format((fit_left, fit_upper, fit_right, fit_lower), (source_left, source_upper, source_right, source_lower)))
            target_buffer[fit_upper:fit_lower, fit_left:fit_right, :num_source_channels] = source_buffer[source_upper:source_lower, source_left:source_right]
        else:
            raise TypeError("Pixels in source have more channels than pixels in target, they cannot be pasted")
