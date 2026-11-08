"""Focused format, topology and native-codec checks. Run with unittest discover."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from skybox.models import FACE_ORDER, PixelFace, ToolError
from skybox.formats import parse_iwi, parse_dds
from skybox.nvtt import Codec
from skybox.images import geometry, split_atlas, panorama, atlas
from skybox.pipeline import Job, run
from skybox.document import Source, Encoding

class Workflows(unittest.TestCase):
    def test_topology_split_alpha_and_seams(self):
        from skybox.topology import GUTTER_ATLAS_FACE_CELLS, CUBE_SEAMS
        from skybox.images import edge_positions
        size, gutter = 32, 4
        rgb = np.zeros((3*size+2*gutter, 4*size+2*gutter, 4), np.uint8)
        alpha = np.zeros(rgb.shape[:2], np.uint8)
        for index, suffix in enumerate(FACE_ORDER):
            col, row = GUTTER_ATLAS_FACE_CELLS[suffix]
            x, y = gutter+col*size, gutter+row*size
            rgb[y:y+size, x:x+size, :3] = [20+index*30, 100, 170]
            rgb[y:y+size, x:x+size, 3] = 0  # Data alpha must never darken RGB.
            alpha[y:y+size, x:x+size] = np.arange(size, dtype=np.uint8)[None, :]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            Image.fromarray(rgb).save(p/'rgb.png')
            Image.fromarray(alpha).save(p/'alpha.png')
            n, g, faces = split_atlas(p/'rgb.png', p/'alpha.png')
            self.assertEqual((n, g), (size, gutter))
            for index, suffix in enumerate(FACE_ORDER):
                np.testing.assert_array_equal(faces[suffix].rgb[16,16], [20+index*30,100,170])
                np.testing.assert_array_equal(faces[suffix].alpha, np.broadcast_to(np.arange(size,dtype=np.uint8), (size,size)))
            for af, aside, bf, bside, reverse in CUBE_SEAMS:
                av = faces[af].rgb.reshape(-1,3)[edge_positions(aside,size,1).ravel()]
                bv = faces[bf].rgb.reshape(-1,3)[edge_positions(bside,size,1).ravel()]
                if reverse: bv=bv[::-1]
                np.testing.assert_array_equal(av[4:-4],bv[4:-4])

    def test_bc3_data_alpha_and_pipeline(self):
        size = 16
        rgb = np.full((size,size,3), [180,120,90], dtype=np.uint8)
        alpha = np.tile(np.arange(size,dtype=np.uint8)*17,(size,1))
        with Codec() as codec:
            encoded = codec.encode(PixelFace(rgb,alpha), b'DXT5')
            decoded = codec.decode(encoded)
            self.assertLessEqual(np.abs(decoded.rgb.astype(int)-rgb).max(), 4)
            self.assertLessEqual(np.abs(decoded.alpha.astype(int)-alpha).max(), 19)
            np.testing.assert_allclose(decoded.rgb[:,0], rgb[:,0], atol=4)
            self.assertEqual(int(decoded.alpha[0,0]), 0)
        faces = {s: PixelFace(rgb.copy(), alpha.copy()) for s in FACE_ORDER}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            atlas(faces).save(p/'rgb.png')
            atlas(faces,True).save(p/'alpha.png')
            result=run(Job('iwi', Source('atlas',p/'rgb.png',p/'alpha.png'), Encoding(b'DXT5'),
                           output=p/'out', name='rgb', game='MW3'), lambda event: None, lambda face, value: None)
            self.assertEqual(result.paths, [p/'out/rgb.iwi'])
            self.assertEqual(list((p/'out').iterdir()), result.paths)
            cube=parse_iwi(p/'out/rgb.iwi')
            self.assertEqual(cube.version,8)
            run(Job('dds', Source('iwi',p/'out/rgb.iwi'), output=p/'out', name='rgb',
                    policy='preserve', native=cube.faces), lambda event: None, lambda face,value: None)
            for suffix,face in zip(FACE_ORDER,cube.faces):
                self.assertEqual(parse_dds(p/f'out/rgb_{suffix}.dds'),face)
            with self.assertRaises(ToolError):
                run(Job('iwi', Source('atlas',p/'rgb.png'), Encoding(b'DXT5'), output=p/'missing', name='rgb'),
                    lambda event: None, lambda face, value: None)
            self.assertFalse((p/'missing/rgb.iwi').exists())

    def test_panorama_orientation(self):
        colors = [(240,20,20),(20,240,20),(20,20,240),(240,240,20),(240,20,240),(20,240,240)]
        faces={s:PixelFace(np.full((16,16,3),color,np.uint8)) for s,color in zip(FACE_ORDER,colors)}
        pixels=np.array(panorama(faces))
        for x,index in ((0,2),(16,1),(32,3),(48,0)):
            np.testing.assert_array_equal(pixels[16,x],colors[index])
        np.testing.assert_array_equal(pixels[0,0],colors[4])
        np.testing.assert_array_equal(pixels[-1,0],colors[5])

    def test_bad_geometry(self):
        with self.assertRaises(ToolError):geometry(100,100)
        with self.assertRaises(ToolError):geometry(129,96)


if __name__ == '__main__':
    unittest.main()
