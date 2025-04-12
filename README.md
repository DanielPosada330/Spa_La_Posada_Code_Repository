# Spa_La_Posada_Excel_Automation
Welcome to the code repository of Spa La Posada! This is where the code and magic happens with the automation of reports and other business functions for the business occur. Below will be an explanation of what technologies are used here at the business, as well list out the projects within the repo and what their purposes are.

Each project will house its own README file, so if you need more information for those particular projects, please refer to each project's respective documentation.

## Technologies used at Spa La Posada
1. Python
    a. Main programming language used as we will be dealing with data, dataframes, automation and Excel. As of now the repo is using Python version 3.12, however please refer to the requirements.txt file for the correct version.
2. UV - https://github.com/astral-sh/uv
    a. This is a package manager to replace Pip and has been shown to be 10-100x faster. UV can also be used to set up a developer environment, making reproduceability easier by setting the python version, able to create a requirements.txt file, create a virtual environment easily etc.
3. Polars - https://docs.pola.rs/api/python/stable/reference/dataframe/index.html
    a. This will be our dataframe technology of choice. While Pandas is the most readily used and commmon dataframe technology, Polars will be used in this project for not only a learning opportunity, but to showcase the speed differentials between the two technologies.

# Projects at Spa La Posada
## Zenoti Biweekly Automation Report
The purpose of this project is to construct an automation script for Spa La Posada's current excel process to help expedite their processes while connecting to Zenoti's API to help facilitate the automation of their biweekly stock report for the 3 store locations of McAllen, Harlingen and Brownsville, all located in Texas. 
