from mutagen.mp4 import MP4
import shutil

input_orig = r'C:\temp\test.mp4'
output_desktop = r'C:\Users\lasis\Desktop\test_gps.mp4'

if not shutil.copy2(input_orig, output_desktop.replace('_gps.mp4', '_copy.mp4')):
    print('Copy failed')
else:
    f = MP4(output_desktop.replace('_gps.mp4', '_copy.mp4'))
    f['\xa9xyz'] = '56.115437,10.157172'
    f.save(output_desktop)
    print(f'GPS added: {output_desktop}')
