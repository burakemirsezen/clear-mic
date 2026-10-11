from PIL import Image,ImageDraw
def image():
    im=Image.new('RGBA',(64,64),(18,28,43,255));d=ImageDraw.Draw(im)
    d.rounded_rectangle((24,10,40,38),radius=8,fill='#62dfbd');d.arc((17,22,47,48),0,180,fill='#62dfbd',width=4);d.line((32,48,32,55),fill='#62dfbd',width=4);d.line((23,56,41,56),fill='#62dfbd',width=4)
    return im
