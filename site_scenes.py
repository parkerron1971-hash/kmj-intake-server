"""site_scenes.py — THE SCENE LIBRARY (2026-11-08, "Teaching Chief to Build").

Measured on four live pages: both hand-built pages have real photos and a
first screen near 200px; both builder pages have neither, and no pinned scene.
The object library holds 46 pieces and none of them holds the page still while
the scroll tells something, because writing that from scratch inside one build
is risky, and a mistake is a long blank scroll.

So scenes are library objects: written once, tested, and added to the finished
page by the server, so the model only places the words and photos. There is one
for every photo count, because most owners have few:

    scene-lines    no photos: the owner's own short lines at poster size
    scene-reveal   one strong photo: a small window opens to the whole screen
    scene-wall     six or more photos: the page pulls back from one to all

ORIGINAL WORK. These are written here for this library. They take no code,
words or layout from any other site, and they use only the browser's own
scrolling, so no animation library's license is involved (GSAP's bars competing
no-code animation builders; see __tests__/test_site_scenes.py).

THE PAGE IS WHOLE WITHOUT THEM MOVING. At rest a scene is a plain stack with
everything visible. Only the script turns it on (.sxo-live), and it stays off
under reduced motion, on a very short screen, and inside a clipped parent,
where a pin could not hold and the visitor would get a long blank scroll.

SWITCH: SITE_SCENES=on lets the Director choose them. Off (the default), the
catalog leaves them out, so no blueprint can name one.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List


def scenes_enabled() -> bool:
    return (os.environ.get("SITE_SCENES") or "off").strip().lower() in ("on", "1", "true", "yes")


def _scene_js(selector: str, frame: str) -> str:
    """The shared frame: turn on only where a pin can hold, then draw from one
    number, p, how far through the scene the visitor has scrolled (0 to 1)."""
    return (
        "(function(){var els=[].slice.call(document.querySelectorAll('" + selector + "'));"
        "if(!els.length||!window.requestAnimationFrame||innerHeight<420)return;"
        "if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)return;"
        "var cuts=function(n){var s=getComputedStyle(n);return /hidden|auto|scroll/.test(s.overflow+s.overflowX+s.overflowY)};"
        "var clipped=function(el){var b=document.body,h=document.documentElement,p=el.parentElement;"
        "for(;p&&p!==b&&p!==h;p=p.parentElement){if(cuts(p))return true}"
        "return cuts(b)&&cuts(h)};"
        "els=els.filter(function(el){return !clipped(el)});if(!els.length)return;"
        "els.forEach(function(el){el.classList.add('sxo-live')});"
        "var c=function(v){return v<0?0:v>1?1:v},busy=false;"
        "function draw(){busy=false;var vh=innerHeight,vw=document.documentElement.clientWidth;"
        "els.forEach(function(el){var r=el.getBoundingClientRect();if(r.bottom<-50||r.top>vh+50)return;"
        "var p=c(-r.top/Math.max(1,r.height-vh));" + frame + "})}"
        "addEventListener('scroll',function(){if(!busy){busy=true;requestAnimationFrame(draw)}},{passive:true});"
        "addEventListener('resize',draw);addEventListener('load',draw);draw()})();"
    )


SCENES: List[Dict[str, Any]] = [
    dict(
        key="scene-lines",
        name="Scene: poster lines",
        intent="the page holds still while the owner's own short lines fill in, one after another, at poster size",
        use_when=("the opening or the turning point of a page with NO photos to spare: two to four "
                  "short lines in the owner's own words, about three words each, no word over ten "
                  "letters, plus one plain closing sentence. The lines size themselves to fill the "
                  "screen, so the longest line sets the size. Make the first line the page's h1 when "
                  "this is the opening. Not for a long sentence, and not for a list of services."),
        aliases=("poster lines scene", "pinned lines", "scene lines"),
        html="""<div class="sxo sxo-scl" data-sx-object="scene-lines" data-overlap-ok>
  <div class="sxo-scl-pin">
    <p class="sxo-scl-line">Slow hands.</p>
    <p class="sxo-scl-line">Real clay.</p>
    <p class="sxo-scl-line">Nothing rushed.</p>
    <p class="sxo-scl-end">Every piece is thrown here, in the back of the studio.</p>
  </div>
</div>""",
        css=""".sxo-scl{position:relative}
.sxo-scl-pin{display:grid;align-content:center;gap:clamp(.1rem,.8vw,.7rem);min-height:60vh;padding:clamp(2rem,6vh,4rem) clamp(1rem,4vw,3rem)}
.sxo-scl-line{margin:0;font-family:var(--_display);font-size:clamp(3rem,12.5vw,13.5rem);line-height:.92;letter-spacing:-.02em;text-transform:uppercase;overflow-wrap:anywhere}
.sxo-scl-end{margin:clamp(1rem,3vh,2rem) 0 0;max-width:46ch;font-size:clamp(1.05rem,1.6vw,1.35rem);line-height:1.45}
.sxo-scl.sxo-live{height:calc(100vh + var(--n,3)*70vh);height:calc(100svh + var(--n,3)*70svh)}
.sxo-scl.sxo-live .sxo-scl-pin{position:sticky;top:0;height:100vh;height:100svh;min-height:0;overflow:hidden}
.sxo-scl.sxo-live .sxo-scl-line{width:max-content;max-width:none;white-space:nowrap;overflow-wrap:normal}
.sxo-scl.sxo-live .sxo-scl-line{-webkit-text-fill-color:transparent;-webkit-background-clip:text;background-clip:text;
  background-image:linear-gradient(90deg,currentColor 0 calc(var(--f,0)*100%),color-mix(in srgb,currentColor 16%,transparent) calc(var(--f,0)*100%) 100%)}
.sxo-scl.sxo-live .sxo-scl-line:nth-last-child(2){color:var(--_accent)}
.sxo-scl.sxo-live .sxo-scl-end{opacity:var(--e,0);transform:translateY(calc((1 - var(--e,0))*18px))}
@media (max-width:640px){.sxo-scl-line{font-size:clamp(2.5rem,14.5vw,5rem)}}""",
        js=_scene_js(
            ".sxo-scl",
            "var ls=el.querySelectorAll('.sxo-scl-line'),n=ls.length||1;el.style.setProperty('--n',n);"
            # the poster fit: the longest line fills the width, and the whole
            # block fits the screen, whatever font and word lengths it gets
            "var size=vw+'x'+vh;if(el._fit!==size&&ls.length){el._fit=size;"
            "var pin=el.querySelector('.sxo-scl-pin'),cs=getComputedStyle(pin),en=el.querySelector('.sxo-scl-end');"
            "var aw=pin.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);"
            "var ah=pin.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom)-(en?en.offsetHeight+28:0);"
            "var j,wide=0;for(j=0;j<ls.length;j++){ls[j].style.fontSize='100px';wide=Math.max(wide,ls[j].offsetWidth)}"
            "var fs=Math.floor(Math.min(aw/Math.max(1,wide)*100,ah/(n*1.02)));"
            # too long to be a poster: stay the plain stack, never tiny type
            "if(fs<28){el.classList.remove('sxo-live');el.style.removeProperty('--n');"
            "for(j=0;j<ls.length;j++){ls[j].style.fontSize=''}return}"
            "for(j=0;j<ls.length;j++){ls[j].style.fontSize=fs+'px'}}"
            "for(var i=0;i<ls.length;i++){var a=i/n*.84,b=(i+1)/n*.84;"
            "ls[i].style.setProperty('--f',c((p-a)/(b-a)).toFixed(3))}"
            "el.style.setProperty('--e',c((p-.86)/.1).toFixed(3));"),
        phone="the lines stay big and fill the screen, stacked; the pin is a little shorter",
    ),
    dict(
        key="scene-reveal",
        name="Scene: the window opens",
        intent="one real photo starts as a small window and opens to fill the whole screen as the page holds still, then one line lands on it",
        use_when=("the single strongest real photo a business has, with people or the work in it, and "
                  "one short line in the owner's words. Needs one sharp, wide photo; never a logo or a "
                  "flyer. Not when the photo is small or soft, since it ends up filling the screen."),
        aliases=("window scene", "opening window", "scene reveal"),
        html="""<div class="sxo sxo-scr" data-sx-object="scene-reveal" data-overlap-ok>
  <div class="sxo-scr-pin">
    <figure class="sxo-scr-frame"><img src="https://example.com/wheel.jpg" alt="Hands lifting a bowl off the wheel" width="1600" height="1000"></figure>
    <p class="sxo-scr-line">Made by hand, one at a time.</p>
  </div>
</div>""",
        css=""".sxo-scr{position:relative}
.sxo-scr-pin{position:relative;display:grid;gap:clamp(.8rem,2vh,1.4rem)}
.sxo-scr-frame{margin:0;overflow:hidden}
.sxo-scr-frame img{display:block;width:100%;height:auto;aspect-ratio:16/10;object-fit:cover}
.sxo-scr-line{margin:0;font-family:var(--_display);font-size:clamp(2rem,6vw,6rem);line-height:1;letter-spacing:-.01em;text-wrap:balance}
.sxo-scr.sxo-live{height:280vh;height:280svh}
.sxo-scr.sxo-live .sxo-scr-pin{position:sticky;top:0;display:block;height:100vh;height:100svh;overflow:hidden}
.sxo-scr.sxo-live .sxo-scr-frame{position:absolute;inset:0;clip-path:inset(calc(var(--c,1)*30%) calc(var(--c,1)*28%) round calc(var(--c,1)*20px))}
.sxo-scr.sxo-live .sxo-scr-frame::after{content:"";position:absolute;inset:0;background:rgba(0,0,0,calc(var(--e,0)*.48))}
.sxo-scr.sxo-live .sxo-scr-frame img{height:100%;aspect-ratio:auto;transform:scale(calc(1 + var(--c,1)*.22))}
.sxo-scr.sxo-live .sxo-scr-line{position:absolute;left:clamp(1rem,5vw,4rem);right:clamp(1rem,5vw,4rem);bottom:clamp(2rem,9vh,6rem);color:rgba(255,255,255,1);
  opacity:var(--e,0);transform:translateY(calc((1 - var(--e,0))*22px))}
@media (max-width:640px){.sxo-scr-line{font-size:clamp(1.9rem,10vw,3rem)}
  .sxo-scr.sxo-live .sxo-scr-frame{clip-path:inset(calc(var(--c,1)*30%) calc(var(--c,1)*14%) round calc(var(--c,1)*16px))}}""",
        js=_scene_js(
            ".sxo-scr",
            "var o=c(p/.68);el.style.setProperty('--c',(1-(1-Math.pow(1-o,3))).toFixed(4));"
            "el.style.setProperty('--e',c((p-.62)/.2).toFixed(3));"),
        phone="the window starts narrower and opens the same way; the line sits low on the photo",
    ),
    dict(
        key="scene-wall",
        name="Scene: the wall of photos",
        intent="the page holds still and pulls back from one real photo to a whole wall of them while one line of the owner's words crosses it",
        use_when=("a business whose people or work are its proof, with SIX OR MORE real photos on file: "
                  "a church, a salon, a shop, a crew. Put the most human photo in the middle of the list, "
                  "since the scene starts on it. One sentence in the owner's words crosses the wall, and "
                  "one short line closes it. Never repeat a photo to fill the wall, and never use it with "
                  "fewer than six."),
        aliases=("photo wall scene", "wall of photos", "scene wall"),
        html="""<div class="sxo sxo-scw" data-sx-object="scene-wall" data-overlap-ok>
  <div class="sxo-scw-pin">
    <div class="sxo-scw-wall">
      <figure><img src="https://example.com/a.jpg" alt="The kiln room in morning light" width="900" height="700"></figure>
      <figure><img src="https://example.com/b.jpg" alt="A student centering clay" width="900" height="700"></figure>
      <figure><img src="https://example.com/c.jpg" alt="Shelves of drying bowls" width="900" height="700"></figure>
      <figure><img src="https://example.com/d.jpg" alt="Mara teaching at the wheel" width="900" height="700"></figure>
      <figure><img src="https://example.com/e.jpg" alt="Glaze test tiles on the bench" width="900" height="700"></figure>
      <figure><img src="https://example.com/f.jpg" alt="Friends at the Saturday open studio" width="900" height="700"></figure>
    </div>
    <p class="sxo-scw-line">Everyone who comes through that door leaves with clay on their hands.</p>
    <p class="sxo-scw-end">This is the studio.</p>
  </div>
</div>""",
        css=""".sxo-scw{position:relative}
.sxo-scw-pin{position:relative;display:grid;gap:clamp(.8rem,2vh,1.4rem)}
.sxo-scw-wall{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(4px,.5vw,8px)}
.sxo-scw-wall figure{margin:0;overflow:hidden}
.sxo-scw-wall img{display:block;width:100%;height:100%;aspect-ratio:4/3;object-fit:cover}
.sxo-scw-line{margin:0;font-family:var(--_display);font-size:clamp(1.8rem,4.5vw,4.5rem);line-height:1.04;letter-spacing:-.01em;text-wrap:balance}
.sxo-scw-end{margin:0;font-family:var(--_display);font-size:clamp(1.4rem,3vw,3rem);line-height:1.05}
.sxo-scw.sxo-live{height:480vh;height:480svh}
.sxo-scw.sxo-live .sxo-scw-pin{position:sticky;top:0;display:block;height:100vh;height:100svh;overflow:hidden;background:var(--_ink)}
.sxo-scw.sxo-live .sxo-scw-wall{position:absolute;inset:0;grid-template-columns:repeat(var(--cols,3),minmax(0,1fr));grid-auto-rows:calc(100% / var(--rows,3));will-change:transform}
.sxo-scw.sxo-live .sxo-scw-wall img{aspect-ratio:auto}
.sxo-scw.sxo-live .sxo-scw-pin::after{content:"";position:absolute;inset:0;background:rgba(0,0,0,var(--sh,.1));pointer-events:none}
.sxo-scw.sxo-live .sxo-scw-line{position:absolute;z-index:1;top:50%;left:0;width:max-content;max-width:none;white-space:nowrap;
  font-size:clamp(3rem,11vw,12rem);color:rgba(255,255,255,1);text-wrap:nowrap}
.sxo-scw.sxo-live .sxo-scw-end{position:absolute;z-index:1;left:clamp(1rem,5vw,4rem);right:clamp(1rem,5vw,4rem);bottom:clamp(2rem,9vh,6rem);
  font-size:clamp(2.2rem,7vw,7rem);color:rgba(255,255,255,1);opacity:var(--e,0);transform:translateY(calc((1 - var(--e,0))*22px))}
@media (max-width:640px){.sxo-scw-wall{grid-template-columns:repeat(2,minmax(0,1fr))}
  .sxo-scw.sxo-live{height:400vh;height:400svh}}""",
        js=_scene_js(
            ".sxo-scw",
            "var w=el.querySelector('.sxo-scw-wall'),ln=el.querySelector('.sxo-scw-line'),pin=el.querySelector('.sxo-scw-pin');"
            "var ks=w.children,n=ks.length||1,cols=vw<=640?(n>8?3:2):(n>9?4:3);"
            "el.style.setProperty('--cols',cols);el.style.setProperty('--rows',Math.ceil(n/cols));"
            "var k=ks[Math.floor((n-1)/2)],cx=k.offsetLeft+k.offsetWidth/2,cy=k.offsetTop+k.offsetHeight/2;"
            "var q=1-Math.pow(1-c((p-.04)/.7),3),m=1-q;"
            "var S=Math.max(vw/Math.max(1,k.offsetWidth),vh/Math.max(1,k.offsetHeight));"
            "w.style.transformOrigin=cx+'px '+cy+'px';"
            "w.style.transform='translate3d('+(m*(vw/2-cx)).toFixed(1)+'px,'+(m*(vh/2-cy)).toFixed(1)+'px,0) scale('+(1+m*(S-1)).toFixed(4)+')';"
            "var t=c((p-.2)/.64),x=vw-t*(vw+ln.scrollWidth);"
            "ln.style.transform='translate3d('+x.toFixed(1)+'px,-50%,0)';"
            "ln.style.opacity=p>.86?0:1;"
            "pin.style.setProperty('--sh',(.08+.48*c((p-.12)/.14)-.14*c((p-.84)/.1)).toFixed(3));"
            "el.style.setProperty('--e',c((p-.86)/.1).toFixed(3));"),
        phone="two columns of photos; the same pull back, and the line still crosses the screen",
    ),
]

SCENE_KEYS = tuple(s["key"] for s in SCENES)

DIRECTOR_RULE = (
    "SCENES (the three scene-* objects): one moment the visitor remembers, where the "
    "page holds still while the scroll tells something. A page gets AT MOST ONE scene, "
    "on SIGNATURE or WORLD only, never on PLAIN. Choose by the real photos on file: "
    "scene-lines for none, scene-reveal for one strong photo, scene-wall for six or "
    "more. Name it on the OBJECTS line, and make it the blueprint's signature moment."
)
