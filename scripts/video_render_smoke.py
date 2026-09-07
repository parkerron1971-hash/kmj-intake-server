"""Local/CI rendered artifact fixture, with no network media or AI credentials."""
import sys,json,subprocess,shutil
from pathlib import Path
from uuid import UUID
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from video_studio_models import Composition,Scene
from video_hyperframes import compile_project,RUNTIME

out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
for fmt in ['landscape','portrait']:
    folder=out/fmt;folder.mkdir(exist_ok=True);(folder/'assets').mkdir(exist_ok=True)
    art=Image.new('RGB',(900,700),'#142844');d=ImageDraw.Draw(art);d.rectangle((70,70,830,630),outline='#4BA9FF',width=12);d.text((120,310),'Solutionist / render fixture',fill='white')
    art.save(folder/'assets/photo.png');aid='11111111-1111-4111-8111-111111111111'
    scenes=[Scene(id='intro',layout='title',title='Your story.\nBeautifully told.',subtitle='Created with Chief.',eyebrow='SOLUTIONIST',seconds=4),
      Scene(id='photo',layout='split',title='Make it yours.',subtitle='Use your own images.',seconds=4,asset_id=aid,motion='push'),
      Scene(id='features',layout='features',title='From idea to video.',seconds=4,points=['Describe your idea','Review the scenes','Create your video']),
      Scene(id='stat',layout='stat',title='A verified number',seconds=4,statistic=42,suffix='%'),
      Scene(id='quote',layout='quote',title='“Every problem has a solution.”',seconds=4),
      Scene(id='full',layout='image',title='Keep the full picture.',seconds=4,asset_id=aid),
      Scene(id='end',layout='closing',title='Ready when you are.',subtitle='Start your next story',seconds=4)]
    spec=Composition(title='Video worker verification',format=fmt,scenes=scenes)
    compile_project(spec,folder,{aid:{'path':'assets/photo.png','mime_type':'image/png'}},{})
    (folder/'fixture.json').write_text(spec.model_dump_json(indent=2))
print(str(out))
