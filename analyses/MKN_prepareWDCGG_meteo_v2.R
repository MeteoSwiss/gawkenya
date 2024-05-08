###########################################
#
# read meteo data from Mount Kenya, hourly
# data provided by Joerg Klausen, downloaded from Joerg's github folder
#
# purpose:  prepares quicklooks
#           prepares file for submission to WDCGG, to accompany CO2, CH4, and CO data submission
#
# mst, 03.05.2024
#
###########################################


##########################
# libraries used #
##########################
library(chron)
##########################

# generate recent date, required for data export filename generation
sys.date <- as.character(Sys.Date())
today <- paste(substring(sys.date, 3, 4), substring(sys.date, 6, 7), substring(sys.date, 9, 10), sep="")

## load tools
source("C:\\Users\\mst\\Documents\\R_project\\functions\\mst.R")


####################################################################################################################################
# INPUT SECTION
####################################################################################################################################

##################
# ENTER GAW ID for header (capital letters)
##################
gaw_id <- "MKN"
##################

################
# ENTER year of export
################
exyear <- 2023
################

##########
# ENTER PATH(s)
##########
pathin <- "C:\\Users\\mst\\Documents\\GAW\\data\\MKN\\meteo\\"
pathout <- "C:\\Users\\mst\\Documents\\GAW\\data\\MKN\\analysis\\WDCGG_submission\\"
#
dir.create(paste(pathout, exyear, sep=""), showWarnings=F) 
######

##########
# ENTER pattern, input file
##########
pattern <- ".csv"
# datfile <- "MKN_1h_21-12-02_to_23-02-01.csv" 
##########

################
# ENTER number of decimal places
################
d <- 2
################

################
# ENTER FURTHER INPUT FOR DATAFILE
################
latitude = -0.0621999986
longitude = 37.2971992493
elevation = 3678
intake_height = 10
altitude <- elevation+intake_height
################

####################################################################################################################################
# END INPUT SECTION
####################################################################################################################################




####################################################################################################################################
# IMPORT SECTION
###################################################################################################################################################

# find file
fn.mkn <- list.files(path=paste(pathin, exyear, sep=""), pattern = pattern, all.files=FALSE, full.names=T, recursive=F); fn.mkn # pattern=NULL

mkndat <- read.table(file=fn.mkn, header=T, sep=",", na.strings="")
   
dim(mkndat)
names(mkndat)
str(mkndat)
head(mkndat)

####################################################################################################################################
# END IMPORT SECTION
###################################################################################################################################################




################################################
# TIMESTAMP SECTION
################################################

mkndat$day.start <- as.numeric(substring(mkndat$dtm, 9, 10)); mkndat$day.start[1:100]
mkndat$month.start <- as.numeric(substring(mkndat$dtm, 6, 7)); mkndat$month.start[1:100]
mkndat$year.start <- as.numeric(substring(mkndat$dtm, 1, 4)); mkndat$year.start[1:100]
mkndat$hour.start <- as.numeric(substring(mkndat$dtm, 12, 13)); mkndat$hour.start[1:100]

mkndat$date.start <- dates(paste(mkndat$month.start,"/",mkndat$day.start,"/",mkndat$year.start))
mkndat$time.start <- times(paste(mkndat$hour.start,":00:00"))
mkndat$dtm <- chron(dates =mkndat$date.start, times = mkndat$time.start); mkndat$dtm[1:100]

# restrcit to data for the respective year only
reldata <- which(mkndat$year.start == exyear)
datout <- mkndat[c(reldata),]

####################################################################################################################################
# END TIMESTAMP SECTION
###################################################################################################################################################




################################################
# QUICKLOOK SECTION
################################################

lab.month <- unique(mkndat$month.start)
xat <- dates(paste(c(1:12, 1), 1, c(rep(exyear, 12), exyear+1), sep="/"))
xlab <- c(1:12, 1)


win.graph(10, 5)
plot(mkndat$dtm, mkndat$prestah0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "2m pressure (hPa)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourly_prestah0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")


win.graph(10, 5)
plot(mkndat$dtm, mkndat$ta2200h0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "2m temperature (degC)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourly_txx200h0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")


win.graph(10, 5)
plot(mkndat$dtm, mkndat$ua2200h0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "2m relative humidity (%)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourly_uxx200h0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")


win.graph(10, 5)
plot(mkndat$dtm, mkndat$fkl010h0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "10m horizontal wind speed (m/s)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourly_fkl010h0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")


win.graph(10, 5)
plot(mkndat$dtm, mkndat$dkl010h0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "10m horizontal wind direction (deg)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourly_dkl010h0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")


win.graph(10, 5)
plot(mkndat$dtm, mkndat$gre000h0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "2m global radiation (W/m2)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourlygre000h0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")


win.graph(10, 5)
plot(mkndat$dtm, mkndat$rre150h0, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
mtext(side=3, "2m precipitation (mm/h)")
axis(side=1, at=xat, lab=NA)
axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
picname.out <- paste(gaw_id, "_", exyear, "_hourly_rre150h0_v", today, ".png", sep="")
pic.path.file.out <- paste(pathout, exyear, "/meteo/", picname.out, sep="")
savePlot(filename = pic.path.file.out, type = "png")

################################################
# END QUICKLOOK SECTION
################################################





#            ################################################
#            # RENAME SECTION
#            ################################################
#            
#            names(mkndat)[names(mkndat) == "prestah0"] <- "air_pressure"
#            names(mkndat)[names(mkndat) == "dkl010h0"] <- "wind_direction"
#            names(mkndat)[names(mkndat) == "fkl010h0"] <- "wind_speed"
#            names(mkndat)[names(mkndat) == "ua2200h0"] <- "relative_humidity"
#            names(mkndat)[names(mkndat) == "ta2200h0"] <- "air_temperature"
#            names(mkndat)[names(mkndat) == "rre150h0"] <- "precipitation_amount"
#            
#            ################################################
#            # END RENAME SECTION
#            ################################################
#            
#            
#                
#            ##########################################################################################
#            # PLOT AGAIN
#            ##########################################################################################
#            
#            
#            
#            win.graph(10, 5)
#            plot(mkndat$dtm, mkndat$air_pressure, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
#            mtext(side=3, "2m pressure (hPa)")
#            axis(side=1, at=xat, lab=NA)
#            axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
#            legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
#            pic.fn <- paste(pathout, exyear, "/meteo/", gaw_id, "_pressure_hourly_", exyear, "_v",today,".png", sep="")
#            savePlot(filename = pic.fn, type = "png")
#            
#            
#            win.graph(10, 5)
#            plot(mkndat$dtm, mkndat$air_temperature, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
#            mtext(side=3, "2m temperature (degC)")
#            axis(side=1, at=xat, lab=NA)
#            axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
#            legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
#            pic.fn <- paste(pathout, exyear, "/meteo/", gaw_id, "_temperature_hourly_", exyear, "_v",today,".png", sep="")
#            savePlot(filename = pic.fn, type = "png")
#            
#            
#            win.graph(10, 5)
#            plot(mkndat$dtm, mkndat$relative_humidity, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
#            mtext(side=3, "2m relative humidity (%)")
#            axis(side=1, at=xat, lab=NA)
#            axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
#            legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
#            pic.fn <- paste(pathout, exyear, "/meteo/", gaw_id, "_relhum_hourly_", exyear, "_v",today,".png", sep="")
#            savePlot(filename = pic.fn, type = "png")
#            
#            
#            win.graph(10, 5)
#            plot(mkndat$dtm, mkndat$wind_speed, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
#            mtext(side=3, "10m horizontal wind speed (m/s)")
#            axis(side=1, at=xat, lab=NA)
#            axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
#            legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
#            pic.fn <- paste(pathout, exyear, "/meteo/", gaw_id, "_windspeed_hourly_", exyear, "_v",today,".png", sep="")
#            savePlot(filename = pic.fn, type = "png")
#            
#            
#            win.graph(10, 5)
#            plot(mkndat$dtm, mkndat$wind_direction, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
#            mtext(side=3, "10m horizontal wind direction (deg)")
#            axis(side=1, at=xat, lab=NA)
#            axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
#            legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
#            pic.fn <- paste(pathout, exyear, "/meteo/", gaw_id, "_winddir_hourly_", exyear, "_v",today,".png", sep="")
#            savePlot(filename = pic.fn, type = "png")
#            
#            
#            win.graph(10, 5)
#            plot(mkndat$dtm, mkndat$precipitation_amount, pch=20, xaxt="n", cex.axis=1.3, cex.lab=1.4, xlab="month")
#            mtext(side=3, "2m precipitation (mm/h)")
#            axis(side=1, at=xat, lab=NA)
#            axis(side=1, at=xat+15, lab=xlab, tck=0, cex.axis=1.3)
#            legend(x="topright", as.character(exyear), col=1, pch=NA, cex=1.5, bty="n")
#            pic.fn <- paste(pathout, exyear, "/meteo/", gaw_id, "_precip_hourly_", exyear, "_v",today,".png", sep="")
#            savePlot(filename = pic.fn, type = "png")
#            
#            
#            ##########################################################################################
#            # END PLOT AGAIN
#            ##########################################################################################






################################################
# prepare output file in WDCGG compatible format
################################################

        
# generate dataframe without data in it
wdcgg.input <- data.frame(site_gaw_id = gaw_id,
    year=datout$year.start, month=datout$month.start, day=datout$day.start, hour=datout$hour.start, minute=0, second=0,
    wind_direction=datout$dkl010h0, wind_speed=datout$fkl010h0, relative_humidity=round(datout$ua2200h0, 2), air_pressure=datout$prestah0,
    air_temperature=round(datout$ta2200h0, 2),  precipitation_amount=datout$rre150h0,
    latitude=latitude, longitude=longitude, altitude=altitude, elevation=elevation)


# replace NA by -99.9
summary(wdcgg.input$wind_direction)
na <- which(is.na(wdcgg.input$wind_direction)); wdcgg.input$wind_direction[na] <- -99.9
na <- which(is.na(wdcgg.input$wind_speed)); wdcgg.input$wind_speed[na] <- -99.9
na <- which(is.na(wdcgg.input$relative_humidity)); wdcgg.input$relative_humidity[na] <- -99.9
na <- which(is.na(wdcgg.input$air_pressure)); wdcgg.input$air_pressure[na] <- -99.
na <- which(is.na(wdcgg.input$air_temperature)); wdcgg.input$air_temperature[na] <- -99.9
na <- which(is.na(wdcgg.input$precipitation_amount)); wdcgg.input$precipitation_amount[na] <- -99.9



################################################
# end prepare output file 
################################################
    
################################################
# export file with meteo data in WDCGG compatible format
################################################

       ############## export daily data in WDCGG compatible format
        path.file.out <-  paste(pathout, exyear, "/meteo/", gaw_id, "_meteo_hourly_", exyear, "_v", today, ".txt", sep="")
        path.file.out <- paste(path.ex, filename.out, sep="")
        #
        write.table(wdcgg.input, file = path.file.out, append=F, quote=F, sep=" ", na ="NA", dec=".", row.names=F, col.names=T)
        ############## end export hourly data in WDCGG compatible format

#####################################
# end
#####################################


################################################################################################################################################################################################
################################################################################################################################################################################################
