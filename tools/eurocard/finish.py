# Final touch (KiCad python): title block names the EuroCard variant. usage: python.exe finish.py in out
import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
tb = b.GetTitleBlock(); tb.SetTitle("IDS EVS Event-camera Synchronizer (Pico 2, EuroCard 160 x 100)"); b.SetTitleBlock(tb)
pcbnew.SaveBoard(sys.argv[2], b)
