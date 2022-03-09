from platypus import NSGAII, Problem, Real, Integer, InjectedPopulation,GAOperator,HUX, BitFlip, SBX,PM,PCX,nondominated,ProcessPoolEvaluator
# I use platypus library to solve the muli-objective optimization problem:
# https://platypus.readthedocs.io/en/latest/getting-started.html
import pandas as pd
import matplotlib.pyplot as plt
import csv
import math
import datetime as dt
import os
import sys
import pandas as pd
import csv
from pathlib import Path
import json
def NSGA_Operation(path_test):
    ###Decison Variables Stage 2###
    solar_PV_generation = []
    wind_turbine_generation = []
    components_path = os.path.join(path_test,'Energy Components')
    editable_data_path =os.path.join(path_test, 'editable_values.csv')
    representative_days_path= os.path.join(path_test,'ScenarioReduction')
    editable_data = pd.read_csv(editable_data_path, header=None, index_col=0, squeeze=True).to_dict()[1]
    results_folder = os.path.join(path_test,'Operation_results')
    if not os.path.exists(results_folder):
        os.makedirs(results_folder)
    city = editable_data['city']
    use_solar_PV = editable_data['Solar_PV']
    use_wind_turbine = editable_data['Wind_turbines']
    use_battery = editable_data['Battery']
    use_grid = editable_data['Grid']
    use_CHP = editable_data['CHP']
    use_boilers = editable_data['Boiler']
    renewable_percentage = float(editable_data['renewable percentage'])  #Amount of renewables at the U (100% --> 1,mix of 43% grid--> 0.463, mix of 29% grid--> 0.29, 100% renewables -->0)
    representative_day = {}
    num_components = 0
    energy_component_type = 1
    energy_component_number = {}
    if use_boilers=='yes':
        num_components +=1
        boiler_component = pd.read_csv(os.path.join(components_path,'boilers.csv'))
        energy_component_number['boilers']=num_components
        energy_component_type +=1
        CAP_boiler= boiler_component['CAP_boiler (kW)'][int(editable_data['boiler_index'])]
    else:
        CAP_boiler = 0
    if use_CHP=='yes':
        num_components +=1
        CHP_component = pd.read_csv(os.path.join(components_path,'CHP.csv'))
        energy_component_number['CHP']=num_components
        energy_component_type +=1
        CAP_CHP_elect= CHP_component['CAP_CHP_elect_size'][int(editable_data['CHP_index'])]
    else:
        CAP_CHP_elect = 0
    if use_solar_PV=='yes':
        energy_component_number['solar_PV']=num_components
        solar_component = pd.read_csv(os.path.join(components_path,'solar_PV.csv'))
        num_components +=1
        PV_module = float(editable_data['PV_module']) #area of each commercial PV moduel is 1.7 M^2
        roof_top_area = float(editable_data['roof_top_area']) #60% percentage of the rooftop area of all buildings https://www.nrel.gov/docs/fy16osti/65298.pdf
        A_solar = roof_top_area*int(editable_data['solar_index'])
    else:
        A_solar = 0
    if use_wind_turbine=='yes':
        num_components +=1
        wind_component = pd.read_csv(os.path.join(components_path,'wind_turbine.csv'))
        energy_component_number['wind_turbine']=num_components
        A_swept= wind_component['Swept Area m^2'][int(editable_data['wind_index'])]
    else:
        A_swept = 0
    if use_battery=='yes':
        num_components +=1
        battery_component = pd.read_csv(os.path.join(components_path,'battery.csv'))
        energy_component_number['battery']=num_components
        CAP_battery= battery_component['CAP_battery (kWh)'][int(editable_data['battery_index'])]
    else:
        CAP_battery = 0
    if use_grid== 'yes':
        CAP_grid =1  #means we can use the grid the optimization
    else:
        CAP_grid = 0 #means we cannot use the grid the optimization
    lbstokg_convert = 0.453592 #1 l b = 0.453592 kg
    ###System Parameters## #
    year = int(editable_data['ending_year'])
    electricity_prices =  float(editable_data['electricity_price'])/100 #6.8cents/kWh in Utah -->$/kWh
    num_scenarios = int(editable_data['num_scenarios'])
    num_clusters = int(editable_data['Cluster numbers'])+2
    class Operation_EA(Problem):
        def __init__(self,G_T_now,V_wind_now,E_bat_now, electricity_demand_now, heating_demand_new,electricity_EF):
            super(Operation_EA, self).__init__(1, 2, 2)  #Problem(2, 2, 2) to create a problem with two decision variables, two objectives, and two constraints, respectively.
            self.solar_PV_generation= self.solar_pv_calc(A_solar, hour,0,G_T_now,1)[0]
            self.wind_turbine_generation = self.wind_turbine_calc(A_swept, hour,0,V_wind_now,1)[0]
            battery_results = self.battery_calc(electricity_demand_now,hour,E_bat_now,CAP_battery,G_T_now,V_wind_now)
            electricity_demand_new = battery_results[2]
            self.E_bat_new = battery_results[0]
            self.electricity_demand_new = electricity_demand_new
            self.heating_demand = heating_demand_new
            self.electricity_EF = electricity_EF
            self.F_CHP = {} #kWh
            self.F_boilers = {} #kWh
            self.P_Ch_Disch = {} #kWh
            self.P_grid = {} #kWh
            self.objective_cost = {} #$
            self.objective_emission = {} #kg CO2
            self.energy_component_number = {}
            self.types[0] = Real(0, self.CHP(CAP_CHP_elect,0)[5]) #Decision space for CHP fuel rate
            self.constraints[0] = ">=0" # the constraints are equality constraints for electricity balance
            self.constraints[1] = ">=0" # the constraints are equality constraints for heating balance
        def evaluate(self, solution):
            self.F_CHP = solution.variables[0]
            self.F_boilers = self.heating_demand - self.CHP(CAP_CHP_elect,self.F_CHP)[1]
            self.P_grid = self.electricity_demand_new - self.CHP(CAP_CHP_elect,self.F_CHP)[0]
            solution.objectives[0] = self.CHP(CAP_CHP_elect,self.F_CHP)[3] + self.NG_boiler(self.F_boilers,CAP_boiler)[2] + self.P_grid*electricity_prices
            solution.objectives[1] = self.CHP(CAP_CHP_elect,self.F_CHP)[4] + self.NG_boiler(self.F_boilers,CAP_boiler)[3] +self.P_grid*self.electricity_EF #kg CO2
            solution.constraints[0] = self.F_boilers
            solution.constraints[1] = self.P_grid
        def CHP(self,CAP_CHP_elect_size,F_CHP_size):
            BTUtokWh_convert = 0.000293071 # 1BTU = 0.000293071 kWh
            mmBTutoBTU_convert = 10**6
            #UPV_maintenance = float(editable_data['UPV_maintenance']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 7
            #UPV_NG = float(editable_data['UPV_NG']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 21 utah
            #UPV_elect = float(editable_data['UPV_elect']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 21 utah
            NG_prices = float(editable_data['price_NG'])/293.001 #Natural gas price at UoU $/kWh
            electricity_prices =  float(editable_data['electricity_price'])/100 #6.8cents/kWh in Utah -->$/kWh CHANGE
            lifespan_chp = int(CHP_component['Lifespan (year)'][0])
            ###CHP system###
            if CAP_CHP_elect_size==0:
                return 0,0,0,0,0,0,0
            else:
                index_CHP = list(CHP_component['CAP_CHP_elect_size']).index(CAP_CHP_elect_size)
                IC_CHP = CHP_component['IC_CHP'][index_CHP] #investment cost for CHP system $/kW
                CAP_CHP_Q= CHP_component['CAP_CHP_Q'][index_CHP] #Natural gas input mmBTU/hr, HHV
                eff_CHP_therm = CHP_component['eff_CHP_therm'][index_CHP] #Thermal efficiency of CHP system Q/F
                eff_CHP_elect = CHP_component['eff_CHP_elect'][index_CHP] #Electricity efficiency of CHP system P/F
                OM_CHP =CHP_component['OM_CHP'][index_CHP] #cent/kWh to $/kWh. now is $/kWh
                gamma_CHP =CHP_component['gamma_CHP'][index_CHP]*lbstokg_convert #
                E_CHP = F_CHP_size*eff_CHP_elect/100 #Electricty generation of CHP system kWh
                Q_CHP = F_CHP_size*eff_CHP_therm/100 #Heat generation of CHP system kWh
                #salvage_CHP = (lifespan_chp-lifespan_project+lifespan_chp*int(lifespan_project/lifespan_chp))/lifespan_chp
                invest_CHP = IC_CHP*CAP_CHP_elect_size #Investment cost of the CHP system $
                OPC_CHP = NG_prices*F_CHP_size + OM_CHP*E_CHP#O&M cost of CHP system $
                OPE_CHP = gamma_CHP*E_CHP # O&M emission of CHP system kg CO2
                #print('CHP',CAP_CHP_elect_size,IC_CHP,eff_CHP_therm,eff_CHP_elect,OM_CHP,gamma_CHP)
                return E_CHP,Q_CHP,invest_CHP,OPC_CHP,OPE_CHP,CAP_CHP_elect_size/eff_CHP_elect*100,CAP_CHP_elect_size*eff_CHP_therm/eff_CHP_elect
        def NG_boiler(self,F_boilers,_CAP_boiler):
            BTUtokWh_convert = 0.000293071 # 1BTU = 0.000293071 kWh
            mmBTutoBTU_convert = 10**6
            #UPV_maintenance = float(editable_data['UPV_maintenance']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 7
            #UPV_NG = float(editable_data['UPV_NG']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 21 utah
            NG_prices = float(editable_data['price_NG'])/293.001 #Natural gas price at UoU $/kWh
            CAP_boiler = _CAP_boiler
            index_boiler = list(boiler_component['CAP_boiler (kW)']).index(CAP_boiler)
            CAP_boiler = boiler_component['CAP_boiler (kW)'][index_boiler]
            ###Natural gas boiler###
            IC_boiler = float(boiler_component['Investment cost $/MBtu/hour'][index_boiler])/1000/BTUtokWh_convert #Natural gas boiler estimated capital cost of $35/MBtu/hour. now unit is $/kW
            landa_boiler = float(boiler_component['Variabel O&M cost ($/mmBTU)'][index_boiler])/mmBTutoBTU_convert/BTUtokWh_convert #O&M cost of input 0.95 $/mmBTU. now unit is 119 $/kWh
            gamma_boiler = float(boiler_component['Natural gas emission factor (kg-CO2/mmBTU)'][index_boiler])/mmBTutoBTU_convert/BTUtokWh_convert #kg-CO2/kWh is emission factor of natural gas
            eff_boiler = float(boiler_component['Boiler Efficiency'][index_boiler]) #efficiency of natural gas boiler
            Q_boiler = eff_boiler*F_boilers #Net heat generation of NG boilers kWh
            #salvage_boiler = 1-(lifespan_boiler-lifespan_project+lifespan_boiler*int(lifespan_project/lifespan_boiler))/lifespan_boiler
            invest_boiler = IC_boiler*CAP_boiler  #Investment cost of boiler in $
            OPC_boiler = (landa_boiler+NG_prices)*F_boilers #O&M cost of boiler $
            OPE_boiler = gamma_boiler*F_boilers #O&M emissions of boiler in kg CO2
            return Q_boiler,invest_boiler,OPC_boiler,OPE_boiler,eff_boiler
        def battery_calc(self,electricity_demand_bat,hour,E_bat_,_CAP_battery,G_T_now,V_wind_now):
            #UPV_maintenance = float(editable_data['UPV_maintenance']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 7
            #lifespan_project = float(editable_data['lifespan_project']) #life span of DES
            deltat = 1 #hour for batteries
            CAP_battery = _CAP_battery
            index_battery =  list(battery_component['CAP_battery (kWh)']).index(CAP_battery)
            eff_bat_ch = battery_component['Battery efficiency charge'][index_battery]
            eff_bat_disch = battery_component['Battery efficiency discharge'][index_battery]
            bat_dod = battery_component['battery depth of discharge'][index_battery] #battery depth of discharge
            lifespan_battery = battery_component['Lifespan (year)'][index_battery]
            E_bat = E_bat_
            renewables_elect =  self.solar_pv_calc(A_solar, hour,0,G_T_now,1)[0] + self.wind_turbine_calc(A_swept, hour,0,V_wind_now,1)[0]
            electricity_demand = electricity_demand_bat
            if renewables_elect>=electricity_demand:
                P_ch_dis_old = renewables_elect - electricity_demand
                electricity_demand = 0
                if P_ch_dis_old>CAP_battery/eff_bat_ch -  E_bat: #Charging the battery
                    P_ch_dis_old = CAP_battery/eff_bat_ch -  E_bat
                E_bat_new= E_bat + eff_bat_ch*P_ch_dis_old*deltat
            elif renewables_elect<electricity_demand: #Diccharging the battery
                P_ch_dis_old = electricity_demand - renewables_elect
                if E_bat- (1-bat_dod)*CAP_battery<0:
                    E_bat_new= E_bat
                    P_ch_dis_old = 0
                elif E_bat- (1-bat_dod)*CAP_battery < 1/eff_bat_disch*P_ch_dis_old*deltat:
                    P_ch_dis_old = eff_bat_disch*E_bat - (1-bat_dod)*CAP_battery
                electricity_demand = electricity_demand - P_ch_dis_old - renewables_elect
                E_bat_new = E_bat - 1/eff_bat_disch*P_ch_dis_old*deltat
            IC_battery =  battery_component['Investment cost ($/kW)'][index_battery] #Battery capital investment cost is 2338 $/kW
            OM_battery = battery_component['Fixed O&M cost  $/kW-year'][index_battery]#fixed battery O&M cost 6$/kW-year
            #invest_battery = (IC_battery*lifespan_project/lifespan_battery +OM_battery*UPV_maintenance)*CAP_battery
            #print('battery',_CAP_battery,IC_battery,OM_battery,eff_bat_disch,eff_bat_ch,bat_dod)
            invest_battery=1
            return E_bat_new,invest_battery,electricity_demand
        def wind_turbine_calc(self,A_swept_size,hour_of_day,electricity_demand_max,V_wind_now,V_max):
            #lifespan_project = float(editable_data['lifespan_project']) #life span of DES
            #UPV_maintenance = float(editable_data['UPV_maintenance']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 7
            ###Wind Turbine###
            wind_component = pd.read_csv(os.path.join(components_path,'wind_turbine.csv'))
            index_wind = list(wind_component['Swept Area m^2']).index(A_swept_size)
            lifespan_wind = int(wind_component['Lifespan (year)'][0]) #lifespan of wind turbines
            cut_in_wind_speed = wind_component['Cut-in Speed'][0] #2.5 m/s is the minimum wind speed to run the wind turbines
            cut_out_wind_speed= wind_component['Cut-out Speed'][0]
            CAP_wind = wind_component['Rated Power kW'][index_wind]
            IC_wind = wind_component['Investment Cost'][index_wind] #Wind turbine capital cost in Utah 2018 1740$/kW
            OM_wind = 44 #fixed wind turbines O&M cost 44$/kW-year
            if V_wind_now<cut_in_wind_speed or  V_wind_now>cut_out_wind_speed:
                V_wind_now = 0
                E_wind = 0
            elif V_wind_now<cut_out_wind_speed and V_wind_now>rated_wind_speed:
                E_wind = rated_power
            else:
                E_wind = rated_power*((V_wind_now-cut_in_wind_speed)/(rated_wind_speed-cut_in_wind_speed))**3
            #salvage_wind = 1-(lifespan_wind-lifespan_project+lifespan_wind*int(lifespan_project/lifespan_wind))/lifespan_wind
            #invest_wind = (IC_wind + OM_wind*UPV_maintenance)*CAP_wind #CAP_wind in kW + investment cost of wind in $
            #print('wind',CAP_wind,C_p,rho,A_swept_size,IC_wind,OM_wind)
            invest_wind=1
            return E_wind, invest_wind
        def solar_pv_calc(self,A_surf_size,hour_of_day,electricity_demand_max,G_T_now,GT_max):
            lifespan_solar = int(solar_component['Lifespan (year)'][0]) #lifespan of solar PV System
            #lifespan_project = float(editable_data['lifespan_project']) #life span of DES
            #UPV_maintenance = float(editable_data['UPV_maintenance']) #https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.85-3273-34.pdf discount rate =3% page 7
            ###Solar PV###
            IC_solar = solar_component['Investment cost ($/Wdc)'][0] #Solar PV capital investment cost is 1.75$/Wdc
            OM_solar = solar_component['Fixed solar PV O&M cost ($/kW-year)'][0] #fixed solar PV O&M cost 18$/kW-year
            PD_solar = solar_component['Power density of solar PV system W/m^2'][0] #Module power density of solar PV system W/m^2
            eff_module = solar_component['Module efficiency'][0] #Module efficiency
            eff_inverter = solar_component['Inverter efficiency'][0] #Inverter efficiency
            CAP_solar = PD_solar*A_surf_size/1000
            A_surf_max = electricity_demand_max/(GT_max*eff_module*eff_inverter/1000)
            #salvage_solar = 1-(lifespan_solar-lifespan_project+lifespan_solar*int(lifespan_project/lifespan_solar))/lifespan_solar
            E_solar = A_surf_size*G_T_now*eff_module*eff_inverter/1000 #Solar generation from PV system (kWh) CHANGE G_T
            if E_solar>CAP_solar:
                E_solar=CAP_solar
            #invest_solar  = (IC_solar*1000*salvage_solar+OM_solar*UPV_maintenance)*CAP_solar #CAP_solar in kW + investment cost of solar in $
            #print('solar',IC_solar,OM_solar,eff_module,eff_inverter,A_surf_size)
            invest_solar=1
            return E_solar,invest_solar,A_surf_max
    def results_extraction(hour, problem,algorithm,solar_PV_generation,wind_turbine_generation,E_bat):
        city = editable_data['city']
        df_operation = {}
        df_cost ={}
        df_object = {}
        df_object_all  = pd.DataFrame(columns = ['Cost ($)','Emission (kg CO2)'])
        df_operation_all = pd.DataFrame(columns = ['CHP Operation (kWh)','Boilers Operation (kWh)','Battery Operation (kWh)','Grid Operation (kWh)','Cost ($)','Emission (kg CO2)'])
        solar_results = {}
        wind_results = {}
        CHP_results = {}
        boiler_results = {}
        battery_results = {}
        grid_results = {}
        i=0

        for s in algorithm.result:
            CHP_results[s] = round(s.variables[0],5)
            if isinstance(CHP_results[s], list):
                CHP_results[s] = float(problem.types[0].decode(CHP_results[s]))
                CHP_results[s] = round(CHP_results[s],5)
            boiler_results[i]= round(problem.heating_demand - problem.CHP(CAP_CHP_elect,CHP_results[s])[1],5)
            grid_results[i]= round(problem.electricity_demand_new - problem.CHP(CAP_CHP_elect,CHP_results[s])[0],5)
            data_object = {'Cost ($)':round(s.objectives[0],5),
            'Emission (kg CO2)':round(s.objectives[1],5)}
            data_operation={'Solar Generation (kWh)':round(solar_PV_generation,5),
            'Wind Generation (kWh)':round(wind_turbine_generation,5),
            'CHP Operation (kWh)':round(CHP_results[s],5),
            'Boilers Operation (kWh)':round(boiler_results[i],5),
            'Battery Operation (kWh)':round(E_bat,5),
            'Grid Operation (kWh)': round(grid_results[i],5),
            'Cost ($)':round(s.objectives[0],5),
            'Emission (kg CO2)':round(s.objectives[1],5)}
            df_object[i] =  pd.DataFrame(data_object,index=[0])
            df_object_all =  df_object_all.append(df_object[i])
            df_operation[i] = pd.DataFrame(data_operation,index=[0])
            df_operation_all =  df_operation_all.append(df_operation[i])
            i += 1
        return df_object_all,df_operation_all

    city_EF =  int(editable_data['city EF'])
    cluster_numbers= int(editable_data['Cluster numbers'])+2
    idf_names = ['ASHRAE901_OfficeMedium_STD2019_Denver','ASHRAE901_Hospital_STD2019_Denver','ASHRAE901_RetailStandalone_STD2019_Denver']
    lat = float(editable_data['Latitude'])
    lon = float(editable_data['Longitude'])
    start_year = int(editable_data['starting_year'])
    end_year = int(editable_data['ending_year'])
    # epw  main files
    weather_data = []
    for year in range(start_year,end_year+1):
        weather_data.append(city+'_'+str(lat)+'_'+str(lon)+'_psm3_60_'+str(year))
    dict_EPWs= {}
    dict_EPWs['AMYs']=weather_data
    for i in range(5):
        if 'TMY'+str(i+1)+'_name' in editable_data.keys():
            TMY_name = editable_data['TMY'+str(i+1)+'_name']
            list_tmys.append(TMY_name)
        if 'FMY'+str(i+1)+'_name'  in editable_data.keys():
            FMY_name = editable_data['FMY'+str(i+1)+'_name']
            list_fmys.append(FMY_name)
    dict_EPWs['TMYs']=list_tmys
    dict_EPWs['FMYs']=list_fmys
    epw_names = []
    for i_temp in range(1,num_scenarios):
        for i_solar in range(num_scenarios):
            epw_names.append('T_'+str(i_temp)+'_S_'+str(i_solar))
    num_scenarios = int(editable_data['num_scenarios'])

    j=0
    for scenario in range(len(epw_names)):
        output_prefix = 'total_'+epw_names[scenario]+'_'
        for represent in range(num_clusters):
            E_bat = {}
            df_object = {}
            df_operation = {}
            data_represent =  pd.read_csv(os.path.join(representative_days_path,output_prefix + 'Represent_days_modified_'+str(represent)+ '.csv'))
            #if represent ==0:
                #print(data_represent['temp_air'][0],data_represent['ghi'][0])
                #print(output_prefix,round(data_represent['Electricity total (kWh)'][0],5),data_represent['Electricity total (kWh)'][0])



    j=0
    for scenario in range(len(epw_names)):
        output_prefix = 'total_'+epw_names[scenario]+'_'
        for represent in range(num_clusters):
            E_bat = {}
            df_object = {}
            df_operation = {}
            data_represent =  pd.read_csv(os.path.join(representative_days_path,output_prefix + 'Represent_days_modified_'+str(represent)+ '.csv'))
            #if represent ==0:
            #    print(output_prefix,round(data_represent['Electricity total (kWh)'][0],5),data_represent['Electricity total (kWh)'][0])
            for hour in range(0,24):
                electricity_demand_now = round(data_represent['Electricity total (kWh)'][hour],5) #kWh
                heating_demand_now =round(data_represent['Heating (kWh)'][hour],5) #kWh
                G_T_now = round(data_represent['gti'][hour],5) #Global Tilted Irradiation (Wh/m^2) in Slat Lake City from TMY3 file for 8760 hr a year on a titled surface 35 deg
                V_wind_now = round(data_represent['wind_speed'][hour],5) #Wind Speed m/s in Slat Lake City from AMY file for 8760 hr in 2019
                electricity_EF = city_EF*renewable_percentage*lbstokg_convert/1000 #kg/kWh
                #print('rep',represent,'demands',electricity_demand_now,heating_demand_now,G_T_now,V_wind_now,electricity_EF)
                if hour==0:
                    E_bat[hour]=0
                #print(G_T_now,V_wind_now,E_bat[hour], electricity_demand_now,heating_demand_now,electricity_EF)
                problem= Operation_EA(G_T_now,V_wind_now,round(E_bat[hour],5), electricity_demand_now,heating_demand_now,electricity_EF)
                #with ProcessPoolEvaluator(int(editable_data['num_processors'])) as evaluator: #max number of accepted processors is 61 by program/ I have 8 processor on my PC
                algorithm = NSGAII(problem,  population_size = int(editable_data['population_size'])) #5000 iteration
                algorithm.run(int(editable_data['num_iterations']))
                E_bat[hour+1] = round(problem.E_bat_new,5)
                df_object_hour,df_operation_hour = results_extraction(hour, problem,algorithm,problem.solar_PV_generation,problem.wind_turbine_generation,E_bat[hour])
                df_object[hour] = df_object_hour.sort_values(by = 'Cost ($)')
                df_operation[hour] =df_operation_hour.sort_values(by = 'Cost ($)')
                #print(hour,df_operation_hour['CHP Operation (kWh)'])
                #print('cost',df_operation_hour['Cost ($)'])
                if hour !=0:
                    df_object[hour] = df_object[hour].add(df_object[hour-1])
                    df_operation[hour] = df_operation[hour].add(df_operation[hour-1])
            file_name = output_prefix+city+'_EF_'+str(float(editable_data['renewable percentage']) )+'_operation_EA_'+str(editable_data['num_iterations'])+'_'+str(editable_data['population_size'])+'_'+str(editable_data['num_processors'])+'_processors'
            results_path = os.path.join(results_folder, file_name)
            if not os.path.exists(results_path):
                os.makedirs(results_path)
            df_object[hour].to_csv(os.path.join(results_path ,output_prefix+'_'+ str(represent)+'_objectives.csv'), index=False)
            df_operation[hour].to_csv(os.path.join(results_path,output_prefix+'_'+ str(represent)+'_sizing.csv'), index=False)

    j = 0

    for key in dict_EPWs.keys():
        for epw_file_name in dict_EPWs[key]:
            output_prefix = 'total_'+epw_file_name+'_'
            for represent in range(num_clusters):
                E_bat = {}
                df_object = {}
                df_operation = {}
                data_represent =  pd.read_csv(os.path.join(representative_days_path,output_prefix + 'Represent_days_modified_'+str(represent)+ '.csv'))
                for hour in range(0,24):
                    electricity_demand_now = round(data_represent['Electricity total (kWh)'][hour],5) #kWh
                    heating_demand_now =round(data_represent['Heating (kWh)'][hour],5) #kWh
                    G_T_now = round(data_represent['gti'][hour],5) #Global Tilted Irradiation (Wh/m^2) in Slat Lake City from TMY3 file for 8760 hr a year on a titled surface 35 deg
                    V_wind_now = round(data_represent['wind_speed'][hour],5) #Wind Speed m/s in Slat Lake City from AMY file for 8760 hr in 2019
                    electricity_EF = city_EF*renewable_percentage*lbstokg_convert/1000 #kg/kWh
                    #print('rep',represent,'demands',electricity_demand_now,heating_demand_now,G_T_now,V_wind_now,electricity_EF)
                    if hour==0:
                        E_bat[hour]=0
                    #print(G_T_now,V_wind_now,E_bat[hour], electricity_demand_now,heating_demand_now,electricity_EF)
                    problem= Operation_EA(G_T_now,V_wind_now,round(E_bat[hour],5), electricity_demand_now,heating_demand_now,electricity_EF)
                    #with ProcessPoolEvaluator(int(editable_data['num_processors'])) as evaluator: #max number of accepted processors is 61 by program/ I have 8 processor on my PC
                    algorithm = NSGAII(problem,  population_size = int(editable_data['population_size'])) #5000 iteration
                    algorithm.run(int(editable_data['num_iterations']))
                    E_bat[hour+1] = round(problem.E_bat_new,5)
                    df_object_hour,df_operation_hour = results_extraction(hour, problem,algorithm,problem.solar_PV_generation,problem.wind_turbine_generation,E_bat[hour])
                    df_object[hour] = df_object_hour.sort_values(by = 'Cost ($)')
                    df_operation[hour] =df_operation_hour.sort_values(by = 'Cost ($)')
                    #print(hour,df_operation_hour['CHP Operation (kWh)'])
                    #print('cost',df_operation_hour['Cost ($)'])
                    if hour !=0:
                        df_object[hour] = df_object[hour].add(df_object[hour-1])
                        df_operation[hour] = df_operation[hour].add(df_operation[hour-1])
                file_name = output_prefix+city+'_EF_'+str(float(editable_data['renewable percentage']) )+'_operation_EA_'+str(editable_data['num_iterations'])+'_'+str(editable_data['population_size'])+'_'+str(editable_data['num_processors'])+'_processors'
                results_path = os.path.join(results_folder, file_name)
                if not os.path.exists(results_path):
                    os.makedirs(results_path)
                #print(results_path)
                df_object[hour].to_csv(os.path.join(results_path ,output_prefix+'_'+ str(represent)+'_objectives.csv'), index=False)
                df_operation[hour].to_csv(os.path.join(results_path,output_prefix+'_'+ str(represent)+'_sizing.csv'), index=False)
                #print(represent,day,df_object[hour])
            j = j+1
